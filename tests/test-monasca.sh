#!/bin/bash

set -o xtrace
set -o errexit


function test_monasca {
    # Run Monasca Tempest plugin against deployment

    # TODO(dszumski): Investigate
    openstack role create monasca-user

    source tempest-venv/bin/activate
    pip install tempest
    # TODO(dszumski): Remove fork when patch is merged
    pip install git+https://github.com/stackhpc/monasca-tempest-plugin.git@feature/configuration
    tempest init monasca_tempest

    # Run metrics tests
    # TODO(dszumski): A small number of these fail occasionally since InfluxDB doesn't always
    # immediately return dimensions after a metric is written. Need to patch Monasca Tempest
    # plugin.
    tempest run --workspace monasca_tempest --regex monasca_tempest_tests.tests.api

    # Run logging tests
    tempest run --workspace monasca_tempest --regex monasca_tempest_tests.tests.log

    # Run some CLI commands
    MONASCA_PROJECT_ID=$(openstack project list --user monasca-agent -f value -c ID)
    monasca metric-list --tenant-id "$MONASCA_PROJECT_ID"
    monasca alarm-list
    monasca notification-list
}

function test_monasca_logged {
    . /etc/kolla/admin-openrc.sh
    # Activate virtualenv to access Monasca client
    . ~/openstackclient-venv/bin/activate
    test_monasca
}

function test_monasca {
    echo "Testing Monasca"
    test_monasca_logged > /tmp/logs/ansible/test-monasca 2>&1
    result=$?
    if [[ $result != 0 ]]; then
        echo "Monasca test failed. See ansible/test-monasca for details"
    else
        echo "Successfully tested Monasca. See ansible/test-monasca for details"
    fi
    return $result
}

test_monasca
