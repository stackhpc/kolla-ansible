#!/bin/bash

set -o xtrace
set -o errexit

# Enable unbuffered output for Ansible in Jenkins.
export PYTHONUNBUFFERED=1


function upgrade {
    RAW_INVENTORY=/etc/kolla/inventory

    source $KOLLA_ANSIBLE_VENV_PATH/bin/activate

    # NOTE(mattcrees): As om_enable_rabbitmq_quorum_queues now defaults to true
    # from Bobcat, we need to perform a migration to durable queues during
    # SLURP upgrades from Antelope to Caracal.
    # TODO(mattcrees): Remove in Dalmatian.
    if [[ $IS_SLURP == "True" ]]; then
        kolla-ansible -i ${RAW_INVENTORY} -vvv prechecks --skip-tags rabbitmq-ha-precheck &> /tmp/logs/ansible/upgrade-prechecks-slurp
        SERVICE_TAGS="heat,keystone,neutron,nova"
        if [[ $SCENARIO == "zun" ]] || [[ $SCENARIO == "cephadm" ]]; then
            SERVICE_TAGS+=",cinder"
        fi
        if [[ $SCENARIO == "scenario_nfv" ]]; then
            SERVICE_TAGS+=",barbican"
        fi
        if [[ $SCENARIO == "ironic" ]]; then
            SERVICE_TAGS+=",ironic"
        fi
        if [[ $SCENARIO == "masakari" ]]; then
            SERVICE_TAGS+=",masakari"
        fi
        if [[ $SCENARIO == "ovn" ]] || [[ $SCENARIO == "octavia" ]]; then
            SERVICE_TAGS+=",octavia"
        fi
        if [[ $SCENARIO == "magnum" ]]; then
            SERVICE_TAGS+=",magnum,designate"
        fi
        kolla-ansible -i ${RAW_INVENTORY} -vvv stop --tags $SERVICE_TAGS --yes-i-really-really-mean-it &> /tmp/logs/ansible/stop
        kolla-ansible -i ${RAW_INVENTORY} -vvv genconfig &> /tmp/logs/ansible/genconfig
        kolla-ansible -i ${RAW_INVENTORY} -vvv rabbitmq-reset-state &> /tmp/logs/ansible/rabbitmq-reset-state
    else
        kolla-ansible -i ${RAW_INVENTORY} -vvv prechecks &> /tmp/logs/ansible/upgrade-prechecks
    fi

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

    if [[ $IS_SLURP == "True" ]]; then
        # Check that all appropriate RabbitMQ queues are now quorum queues.
        kolla-ansible -i ${RAW_INVENTORY} -vvv prechecks --tags rabbitmq-ha-precheck &> /tmp/logs/ansible/rabbitmq-ha-precheck
    fi

    kolla-ansible -i ${RAW_INVENTORY} -vvv post-deploy &> /tmp/logs/ansible/upgrade-post-deploy

    kolla-ansible -i ${RAW_INVENTORY} -vvv validate-config &> /tmp/logs/ansible/validate-config
}


upgrade
