#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright 2026 StackHPC Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from ansible.module_utils.basic import AnsibleModule
import base64
import fnmatch
import glob
import os
import subprocess
import tempfile

__metaclass__ = type

DOCUMENTATION = r"""
---
module: kolla_ansible_password_check
short_description: Check kolla-ansible passwords.yml for leaked secrets
description:
  - Reads a kolla-ansible passwords.yml file and searches the systemd journal
    for any occurrences of the password values, both in plain text and
    base64-encoded (e.g. inside HTTP Basic auth headers).
  - Optionally also searches log files, such as saved kolla-ansible output.
  - Reports which variable names had their secrets found, and where.
  - Fails if any leaked secrets are detected.
  - All secret values are handled internally and never appear in Ansible
    output, logs, or return values — only variable names are ever surfaced.
version_added: "1.0.0"
author:
  - Michal Nasiadka <mnasiadka@gmail.com>
options:
  passwords_file:
    description:
      - Path to the kolla-ansible passwords.yml file on the remote host.
    type: path
    required: true
  min_password_length:
    description:
      - Minimum length a password value must have to be checked.
      - Very short values (e.g. single characters) are skipped to avoid
        false positives.
    type: int
    default: 8
  journalctl_args:
    description:
      - Extra arguments passed verbatim to journalctl
        (e.g. C(--since "1 hour ago")).
      - Do not include C(--no-pager) or C(-g) / C(--grep) as these are added
        automatically.
    type: str
    default: ""
  log_files:
    description:
      - List of log file paths or glob patterns on the remote host to search
        in addition to the journal (e.g. C(/tmp/logs/ansible/*)).
      - Patterns that match no files produce a warning.
    type: list
    elements: str
    default: []
  exclude_log_files:
    description:
      - List of glob patterns for files matched by C(log_files) that should
        not be searched.
    type: list
    elements: str
    default: []
  fail_on_leaked:
    description:
      - Whether to fail the task when leaked secrets are found.
      - Set to C(false) to report leaks without failing, useful for dry-runs.
    type: bool
    default: true
  return_stdout:
    description:
      - When C(true), include the journalctl output for each leaked entry
        in the C(leaked_entries) return value.
      - Has no effect when there are no leaks.
      - Note that journalctl output for a leaked entry will contain the
        secret value. Use C(no_log) on any subsequent tasks that display
        C(leaked_entries) if you need to protect it.
    type: bool
    default: false
  ignore_keys:
    description:
      - List of variable names whose presence in the journal should not be
        treated as a leak.
      - Entries in this list are still checked against the journal; they are
        just excluded from C(leaked_keys), C(leaked_entries), and the failure
        condition.
      - Matched entries are reported separately in C(ignored_leaked_keys) so
        there is a full audit trail of what was intentionally allowed.
    type: list
    elements: str
    default: []
notes:
  - Requires C(journalctl) and C(grep) to be available on the remote host.
  - Must be run with sufficient privileges to read the journal
    (typically requires C(become: true)).
  - The journal and any C(log_files) are read once by a single C(grep -F)
    run that searches for all passwords and their base64 forms at the same
    time.
  - Base64 matching covers a password embedded at any position in a larger
    base64 string (e.g. C(user:password)), by searching for the three
    possible 3-byte alignments of its encoding.
  - The search patterns are written to a temporary file readable only by
    the module user, which is deleted as soon as the search finishes.
  - Values containing newlines are skipped.
  - Secret values are B(never) included in module return data, only variable
    names are returned, making this safe to use without C(no_log).
requirements:
  - journalctl (systemd)
  - PyYAML
"""

EXAMPLES = r"""
- name: Check kolla passwords for journal leaks
  kolla_ansible_password_check:
    passwords_file: /etc/kolla/passwords.yml
  become: true
  register: leak_result

- name: Show which keys leaked
  ansible.builtin.debug:
    msg: "Leaked keys: {{ leak_result.leaked_keys }}"
  when: leak_result.leaked_keys | length > 0

# Non-failing variant for reporting
- name: Audit journal leaks without failing
  kolla_ansible_password_check:
    passwords_file: /etc/kolla/passwords.yml
    fail_on_leaked: false
    journalctl_args: '--since "24 hours ago"'
  become: true
  register: audit_result

# Also search saved kolla-ansible output
- name: Check kolla passwords for journal and log leaks
  kolla_ansible_password_check:
    passwords_file: /etc/kolla/passwords.yml
    log_files:
      - /tmp/logs/ansible/*
    exclude_log_files:
      - /tmp/logs/ansible/test-*
  become: true
"""

RETURN = r"""
leaked_keys:
  description:
    - List of variable names from passwords.yml whose values were found in
      the journal. Never contains the actual secret values.
  type: list
  elements: str
  returned: always
  sample: ["keystone_db_password", "nova_keystone_password"]
base64_leaked_keys:
  description:
    - Subset of C(leaked_keys) whose values were found base64-encoded.
  type: list
  elements: str
  returned: always
  sample: ["prometheus_haproxy_password"]
leaked_sources:
  description:
    - Mapping of leaked variable names to where they were found, either
      C(journal) or a log file path.
  type: dict
  returned: always
  sample: {"prometheus_haproxy_password": ["/tmp/logs/ansible/deploy"]}
checked_count:
  description: Number of password entries that were actually checked.
  type: int
  returned: always
  sample: 42
skipped_count:
  description:
    - Number of entries skipped because their value was empty, null,
      non-string, multi-line, or shorter than min_password_length.
  type: int
  returned: always
  sample: 5
msg:
  description: Human-readable summary of the check result.
  type: str
  returned: always
  sample: "No secrets found in journal or log files. Checked 42 entries."
leaked_entries:
  description:
    - Mapping of leaked variable names to the matching lines, each prefixed
      with its source (C(journal:) or the log file path).
    - Only populated when C(return_stdout: true) and leaks are found.
    - The journalctl output will contain the secret value — treat accordingly.
  type: dict
  returned: when return_stdout is true and leaks are found
  sample: {"keystone_db_password": "Mar 26 ... keystone_db_password=s3cr3t"}
ignored_leaked_keys:
  description:
    - List of variable names that were found in the journal but are present
      in C(ignore_keys) and therefore excluded from C(leaked_keys).
    - Always returned so there is a full audit trail of intentional allowances.
  type: list
  elements: str
  returned: always
  sample: ["deployment_ssh_key"]
ignored_leaked_sources:
  description:
    - Mapping of C(ignored_leaked_keys) to where they were found, either
      C(journal) or a log file path.
  type: dict
  returned: always
  sample: {"database_password": ["/tmp/logs/ansible/deploy", "journal"]}
"""

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def load_passwords(module, passwords_file):
    """Load and parse the kolla passwords YAML file.

    Returns a dict of {variable_name: password_value}.
    Aborts the module on any read/parse error.
    """
    if not os.path.isfile(passwords_file):
        module.fail_json(
            msg="passwords_file not found: {}".format(passwords_file))

    try:
        with open(passwords_file, "r") as fh:
            content = fh.read()
    except OSError as exc:
        module.fail_json(
            msg="Cannot read passwords_file: {}".format(str(exc)))

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        module.fail_json(
            msg="Failed to parse passwords YAML: {}".format(str(exc)))

    if data is None:
        return {}
    if not isinstance(data, dict):
        module.fail_json(
            msg="passwords_file must contain a YAML mapping at the top level"
        )

    return data


def b64_variants(value):
    """Return the base64 forms of value at each of the 3 byte alignments.

    A value embedded in a larger base64 string (e.g. user:password in an
    HTTP Basic auth header) is encoded at one of three alignments depending
    on the length of what precedes it. Only characters derived solely from
    value are kept, so the variants match whatever surrounds it.
    """
    data = value.encode("utf-8")
    variants = set()
    for offset in range(3):
        encoded = base64.b64encode(b"\0" * offset + data).decode("ascii")
        # Drop characters mixed with the preceding/following bytes.
        start = -(-8 * offset // 6)
        end = (8 * (offset + len(data))) // 6
        variants.add(encoded[start:end])
    return variants


def resolve_log_files(module, log_files, exclude_log_files):
    """Expand log_files glob patterns into a sorted list of files."""
    files = set()
    for pattern in log_files:
        matched = [path for path in glob.glob(pattern) if os.path.isfile(path)]
        if not matched:
            module.warn("No log files match {}".format(pattern))
        files.update(matched)
    return sorted(
        path for path in files
        if not any(fnmatch.fnmatch(path, ex) for ex in exclude_log_files)
    )


def grep_sources(module, extra_args, log_files, patterns, only_matching):
    """Search the journal and log_files with a single grep -F run.

    Each result is a (source, text) pair, where source is "journal" or a log
    file path. With only_matching, returns the set of (source, matched
    pattern) pairs, otherwise the list of (source, matching line) pairs.
    """
    journal_cmd = ["journalctl", "--no-pager"]
    if extra_args:
        journal_cmd.extend(extra_args.split())
    # -a: never collapse matches into "Binary file matches".
    # -H/--label: prefix each result with its source; "-" is the journal.
    grep_cmd = ["grep", "-a", "-F", "-H", "--label=journal"]
    if only_matching:
        grep_cmd.append("-o")
    # Longest first, so a path containing ":" is not split too early.
    sources = sorted(["journal"] + log_files, key=len, reverse=True)

    matches = set() if only_matching else []

    # The patterns file holds secret values. NamedTemporaryFile creates it
    # with mode 0600 and deletes it on close.
    with tempfile.NamedTemporaryFile(
        "w", prefix="kolla_password_check_"
    ) as pattern_file, tempfile.TemporaryFile() as errors:
        pattern_file.write("\n".join(patterns) + "\n")
        pattern_file.flush()

        try:
            journal = subprocess.Popen(
                journal_cmd, stdout=subprocess.PIPE, stderr=errors)
            grep = subprocess.Popen(
                grep_cmd + ["-f", pattern_file.name, "--", "-"] + log_files,
                stdin=journal.stdout,
                stdout=subprocess.PIPE,
                stderr=errors,
            )
        except OSError as exc:
            module.fail_json(
                msg="Failed to run leak scan: {}".format(str(exc)))
        # Let journalctl receive SIGPIPE if grep exits early.
        journal.stdout.close()

        for line in grep.stdout:
            line = line.decode("utf-8", errors="replace").rstrip("\n")
            source = next(
                (s for s in sources if line.startswith(s + ":")), None)
            if source is None:
                continue
            result = (source, line[len(source) + 1:])
            if only_matching:
                matches.add(result)
            else:
                matches.append(result)

        grep.wait()
        journal.wait()

        # grep exits 0 = match found, 1 = no match, 2+ = error.
        if journal.returncode != 0 or grep.returncode > 1:
            errors.seek(0)
            module.fail_json(
                msg="Leak scan failed (journalctl {}, grep {}): {}".format(
                    journal.returncode,
                    grep.returncode,
                    errors.read().decode("utf-8", errors="replace").strip(),
                )
            )

    return matches


def run_module():
    module_args = dict(
        passwords_file=dict(type="path", required=True),
        min_password_length=dict(type="int", default=8),
        journalctl_args=dict(type="str", default=""),
        log_files=dict(type="list", elements="str", default=[]),
        exclude_log_files=dict(type="list", elements="str", default=[]),
        fail_on_leaked=dict(type="bool", default=True),
        return_stdout=dict(type="bool", default=False),
        ignore_keys=dict(type="list", elements="str", default=[]),
    )

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True,
    )

    if not HAS_YAML:
        module.fail_json(msg="PyYAML is required for this module.")

    passwords_file = module.params["passwords_file"]
    min_length = module.params["min_password_length"]
    extra_args = module.params["journalctl_args"]
    fail_on_leaked = module.params["fail_on_leaked"]
    return_stdout = module.params["return_stdout"]
    ignore_keys = set(module.params["ignore_keys"])

    passwords = load_passwords(module, passwords_file)
    log_files = resolve_log_files(
        module, module.params["log_files"],
        module.params["exclude_log_files"])

    leaked_keys = []
    base64_leaked_keys = []
    leaked_sources = {}
    leaked_entries = {}
    ignored_leaked_keys = []
    ignored_leaked_sources = {}
    checked_count = 0
    skipped_count = 0

    # Map each search string to the (key, is_base64) pairs it came from.
    patterns = {}
    for key, value in passwords.items():
        # Skip null, non-string, multi-line or suspiciously short values.
        if not isinstance(value, str) or "\n" in value:
            skipped_count += 1
            continue
        if len(value) < min_length:
            skipped_count += 1
            continue

        checked_count += 1
        patterns.setdefault(value, set()).add((key, False))
        for variant in b64_variants(value):
            patterns.setdefault(variant, set()).add((key, True))

    # In check mode we report what *would* be checked without hitting
    # journalctl, since we can't know what the journal contains.
    matched = set()
    if patterns and not module.check_mode:
        matched = grep_sources(module, extra_args, log_files, patterns, True)

    # Map each found key to the sources it was found in.
    found_sources = {}
    base64_keys = set()
    for source, match in matched:
        for key, is_base64 in patterns.get(match, ()):
            found_sources.setdefault(key, set()).add(source)
            if is_base64:
                base64_keys.add(key)
    found_keys = set(found_sources)

    for key in passwords:
        if key not in found_keys:
            continue
        if key in ignore_keys:
            # Found in journal but explicitly allowed — track separately
            # for audit purposes but do not treat as a failure.
            ignored_leaked_keys.append(key)
            ignored_leaked_sources[key] = sorted(found_sources[key])
        else:
            # Only the key name is stored by default — the secret value is
            # intentionally never written to any Ansible data structure
            # unless return_stdout is explicitly requested.
            leaked_keys.append(key)
            leaked_sources[key] = sorted(found_sources[key])
            if key in base64_keys:
                base64_leaked_keys.append(key)

    if return_stdout and leaked_keys:
        # Second pass only for the leaked strings, to collect full lines.
        leaked_set = set(leaked_keys)
        wanted = {}
        for _, match in matched:
            owners = {k for k, _ in patterns.get(match, ())} & leaked_set
            if owners:
                wanted[match] = owners
        lines = grep_sources(module, extra_args, log_files, wanted, False)
        for source, line in lines:
            for match, owners in wanted.items():
                if match in line:
                    for key in owners:
                        leaked_entries.setdefault(key, []).append(
                            "{}:{}".format(source, line))
        leaked_entries = {
            key: "\n".join(lines) + "\n"
            for key, lines in leaked_entries.items()
        }

    where = "journal"
    if log_files:
        where = "journal or {} log file(s)".format(len(log_files))
    if leaked_keys:
        summary = (
            "Leaked secrets found in {} for {} variable(s): {}. "
            "Checked {} entries, skipped {}.".format(
                where,
                len(leaked_keys),
                ", ".join(leaked_keys),
                checked_count,
                skipped_count,
            )
        )
    else:
        summary = (
            "No secrets found in {}. "
            "Checked {} entries, skipped {}.""".format(
                where,
                checked_count,
                skipped_count
            )
        )

    if ignored_leaked_keys:
        summary += " Ignored {} allowed variable(s): {}.".format(
            len(ignored_leaked_keys), ", ".join(ignored_leaked_keys)
        )

    result = dict(
        changed=False,
        leaked_keys=leaked_keys,
        base64_leaked_keys=base64_leaked_keys,
        leaked_sources=leaked_sources,
        leaked_entries=leaked_entries,
        ignored_leaked_keys=ignored_leaked_keys,
        ignored_leaked_sources=ignored_leaked_sources,
        checked_count=checked_count,
        skipped_count=skipped_count,
        msg=summary,
    )

    if leaked_keys and fail_on_leaked:
        module.fail_json(**result)

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
