#!/bin/bash

# Check for CRITICAL, ERROR or WARNING messages in log files.

set -o errexit
set -o pipefail

# Enable unbuffered output for Ansible in Jenkins.
export PYTHONUNBUFFERED=1

declare -a fluentchecks=("got incomplete line before first line" "pattern not matched:" "unreadable. It is excluded and would be examined next time." "Permission denied @ rb_sysopen")

function check_openstack_log_file_for_level {
    # $1: file
    # $2: log level
    # Filter out false positives from logged config options.
    sudo egrep " $2 " $1 | egrep -v "(logging_exception_prefix|rate_limit_except_level)"
}

function check_fluentd_log_file_for_level {
    # $1: file
    # $2: log level
    sudo egrep "\[$2\]:" $1
}

function check_fluentd_log_file_for_content {
    # $1: file
    # $2: content
    sudo egrep "$2" $1
}

function check_fluentd_missing_logs {
    code=0
    for file in $(sudo find /var/log/kolla/ -type f -name '*.log' | grep -v '^$'); do
        case $file in
        /var/log/kolla/ansible.log)
            continue
            ;;
        /var/log/kolla/etcd/etcd.log)
            continue
            ;;
        /var/log/kolla/fluentd/fluentd.log)
            continue
            ;;
        /var/log/kolla/glance-tls-proxy/glance-tls-proxy.log)
            continue
            ;;
        /var/log/kolla/grafana/grafana.log)
            continue
            ;;
        /var/log/kolla/haproxy/*)
            continue
            ;;
        /var/log/kolla/ironic/dnsmasq.log)
            continue
            ;;
        /var/log/kolla/mariadb/mariadb-bootstrap.log)
            continue
            ;;
        /var/log/kolla/mariadb/mariadb-clustercheck.log)
            continue
            ;;
        /var/log/kolla/mariadb/mariadb-upgrade.log)
            continue
            ;;
        /var/log/kolla/neutron/dnsmasq.log)
            continue
            ;;
        /var/log/kolla/neutron-tls-proxy/neutron-tls-proxy.log)
            continue
            ;;
        /var/log/kolla/opensearch/*)
            continue
            ;;
        /var/log/kolla/opensearch-dashboards/*)
            continue
            ;;
        /var/log/kolla/openvswitch/*)
            continue
            ;;
        /var/log/kolla/proxysql/proxysql.log)
            continue
            ;;
        /var/log/kolla/rabbitmq/*upgrade.log)
            continue
            ;;
        /var/log/kolla/redis/*)
            continue
            ;;
        /var/log/kolla/skyline/skyline.log)
            continue
            ;;
        *)
            sudo grep -q "following tail of $file" /var/log/kolla/fluentd/fluentd.log || echo "no match for $file" && code=1
            ;;
        esac
    done
    return $code
}

function check_docker_log_file_for_sigkill {
    sudo journalctl --no-pager -u ${CONTAINER_ENGINE}.service | grep "signal 9"
}

function filter_out_expected_critical {
    # $1: file
    # Filter out expected critical log messages that we do not want to fail the
    # job.

    case $1 in
    */neutron-server.log)
        # Sometimes we see this during shutdown (upgrade).
        # See: https://bugs.launchpad.net/neutron/+bug/1863579
        grep -v "Unhandled error: oslo_db.exception.DBConnectionError" |
        grep -v "WSREP has not yet prepared node for application use" |
        grep -v "Failed to fetch token data from identity server" |
        grep -v "Max connect timeout reached while reaching hostgroup"
        ;;
    *)
        # Sometimes we see this during upgrades of Keystone.
        # Usually in Placement but also in Neutron and Nova.
        # Especially in AIO.
        grep -v "Failed to fetch token data from identity server" |
        grep -v "Identity server rejected authorization necessary to fetch token data"
        ;;
    esac
}

any_critical=0
for level in CRITICAL ERROR WARNING; do
    all_file=/tmp/logs/kolla/all-${level}.log
    # remove the file to avoid collecting duplicates (upgrade, post)
    rm -f $all_file
    any_matched=0
    echo "Checking for $level log messages"
    for f in $(sudo find /var/log/kolla/ -type f); do
        if check_openstack_log_file_for_level $f $level >/dev/null; then
            any_matched=1
            if [[ $level = CRITICAL ]]; then
                if check_openstack_log_file_for_level $f $level | filter_out_expected_critical $f >/dev/null; then
                    any_critical=1
                fi
            fi
            echo $f >> $all_file
            check_openstack_log_file_for_level $f $level >> $all_file
            echo >> $all_file
        fi
    done
    if [[ $any_matched -eq 1 ]]; then
        echo "Found some $level log messages. Matches in $all_file"
    fi
done

if [ -d /var/log/kolla ]; then
    # check fluentd errors (we consider them critical)
    fluentd_log_file=/var/log/kolla/fluentd/fluentd.log
    fluentd_error_summary_file=/tmp/logs/kolla/fluentd-error.log
    if check_fluentd_log_file_for_level $fluentd_log_file error >/dev/null; then
        any_critical=1
        echo "(critical) Found some error log messages in fluentd logs. Matches in $fluentd_error_summary_file"
        check_fluentd_log_file_for_level $fluentd_log_file error > $fluentd_error_summary_file
        echo >> $fluentd_error_summary_file
    fi

    for string in "${fluentchecks[@]}"; do
        fluentd_file=/tmp/logs/kolla/fluentd-errors.log
        if check_fluentd_log_file_for_content $fluentd_log_file "$string" >/dev/null; then
            any_critical=1
            echo "(critical) Found some error log messages in fluentd logs. Matches in $fluentd_file"
            echo "Check: $string" >> $fluentd_file
            check_fluentd_log_file_for_content $fluentd_log_file "$string" >> $fluentd_file
            echo >> $fluentd_file
        fi
    done

    if check_fluentd_missing_logs >/dev/null; then
        any_critical=1
        echo "(critical) Found some missing log files in fluentd logs. Matches in $fluentd_error_summary_file"
        check_fluentd_missing_logs >> $fluentd_error_summary_file
        echo >> $fluentd_error_summary_file
    fi
fi

if check_docker_log_file_for_sigkill >/dev/null; then
    any_critical=1
    echo "(critical) Found containers killed using signal 9 (SIGKILL) in docker logs."
fi

if [[ $any_critical -eq 1 ]]; then
    echo "Found critical log messages - failing job."
    exit 1
fi
