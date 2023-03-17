#!/bin/bash

set -o xtrace
set -o errexit

# Enable unbuffered output for Ansible in Jenkins.
export PYTHONUNBUFFERED=1


function upgrade {
    RAW_INVENTORY=/etc/kolla/inventory

    source $KOLLA_ANSIBLE_VENV_PATH/bin/activate

    kolla-ansible -i ${RAW_INVENTORY} -vvv prechecks &> /tmp/logs/ansible/upgrade-prechecks
    kolla-ansible -i ${RAW_INVENTORY} -vvv pull &> /tmp/logs/ansible/pull-upgrade

    if [[ $SCENARIO == "ovs_split_upgrade" ]]; then
        kolla-ansible -i ${RAW_INVENTORY} -vvv upgrade --skip-tags neutron,openvswitch &> /tmp/logs/ansible/upgrade
        kolla-ansible -i ${RAW_INVENTORY} -vvv upgrade --tags neutron -e neutron_service_limit=neutron-server &> /tmp/logs/ansible/upgrade-neutron-server
        # NOTE(wszumski): We are skipping the process of draining and upgrading each network node separately for simplicity. This could be added later.
        kolla-ansible -i ${RAW_INVENTORY} -vvv upgrade --limit network --tags neutron,openvswitch -e neutron_service_limit='neutron-openvswitch-agent,neutron-dhcp-agent,neutron-l3-agent,neutron-metadata-agent,ironic-neutron-agent' &> /tmp/logs/ansible/upgrade-neutron-network-nodes
        kolla-ansible -i ${RAW_INVENTORY} -vvv upgrade --limit compute --tags neutron,openvswitch &> /tmp/logs/ansible/upgrade-neutron-computes
    else
        kolla-ansible -i ${RAW_INVENTORY} -vvv upgrade &> /tmp/logs/ansible/upgrade
    fi

    # NOTE(yoctozepto): These actions remove the leftovers of the admin port.
    # TODO(yoctozepto): Remove after Zed.
    kolla-ansible -i ${RAW_INVENTORY} -vvv deploy --tags keystone &> /tmp/logs/ansible/upgrade-deploy
    kolla-ansible -i ${RAW_INVENTORY} -vvv post-deploy &> /tmp/logs/ansible/upgrade-post-deploy

    kolla-ansible -i ${RAW_INVENTORY} -vvv validate-config &> /tmp/logs/ansible/validate-config
}


upgrade
