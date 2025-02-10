#!/usr/bin/env python

# Copyright 2016 NEC Corporation
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

# NOTE(r-krcek): As the format of data from PodmanClient are nearly identical
# to data returned by DockerClient. The tests can be ran only on one of the
# clients. (There are certain exceptions but none apply to these tests)


import copy
from importlib.machinery import SourceFileLoader
import os
import sys
from unittest import mock

from docker import errors as docker_error
from oslotest import base


this_dir = os.path.dirname(sys.modules[__name__].__file__)
ansible_dir = os.path.join(this_dir, '..', 'ansible')
kolla_container_facts_file = os.path.join(
    ansible_dir,
    'library', 'kolla_container_facts.py')
kcf = SourceFileLoader('kolla_container_facts',
                       kolla_container_facts_file).load_module()


FAKE_DATA = {
    'containers': [
        {'Created': '2022-06-23T14:30:35.595194629Z',
         'State': {'Status': 'running'},
         'HostConfig': {'NetworkMode': 'host'},
         'Id': '1663dfafec3bb59386e4a024416c8b0a872ae0984c9806322751d14b9f794c56',      # noqa: E501
         'ImageName': 'myregistrydomain.com:5000/ubuntu:16.04',
         'Image': '7528a4009573fa8c5dbf4b6f5fad9f5b8d3a0fb90e22bb1b217211b553eb22cf',   # noqa: E501
         'Labels': {},
         'Name': 'my_container'},
        {'Created': '2022-06-23T14:32:13.17545575Z',
         'State': {'Status': 'exited'},
         'HostConfig': {'NetworkMode': 'host'},
         'Id': '9404fc5f90118ddbbc31bb4c9462ad06aa7163eac1bc6d74c3e978143f10cc0c',      # noqa: E501
         'ImageName': 'myregistrydomain.com:5000/ubuntu:16.04',
         'Image': '15529c81ae4a83084b076a16bc314e1af0b040a937f585311c87863fecc623a3',   # noqa: E501
         'Labels': {},
         'Name': 'exited_container'},
    ],
    'container_inspect': {
        'Config': {
            'Env': ['KOLLA_BASE_DISTRO=ubuntu',
                    'KOLLA_INSTALL_TYPE=binary',
                    'KOLLA_INSTALL_METATYPE=rdo'],
            'Hostname': 'node2',
            'Volumes': {'/var/lib/kolla/config_files/': {}}},
        'Mounts': {},
        'NetworkSettings': {}
    }
}


@mock.patch('docker.DockerClient')
def get_DockerFactsWorker(mod_param, mock_client):
    module = mock.MagicMock()
    module.params = copy.deepcopy(mod_param)
    dfw = kcf.DockerFactsWorker(module)
    return dfw


def construct_container(cont_dict):
    container = mock.Mock()
    container.name = cont_dict['Name']
    container.attrs = copy.deepcopy(cont_dict)
    container.status = cont_dict['State']['Status']
    return container


def get_containers(override=None):
    if override:
        cont_dicts = override
    else:
        cont_dicts = copy.deepcopy(FAKE_DATA['containers'])

    containers = []
    for c in cont_dicts:
        # Only running containers should be returned by the container APIs
        if c['State']['Status'] == 'running':
            containers.append(construct_container(c))

    return containers


class TestContainerFacts(base.BaseTestCase):
    def setUp(self):
        super(TestContainerFacts, self).setUp()
        self.fake_data = copy.deepcopy(FAKE_DATA)

    def test_get_containers_single(self):
        self.dfw = get_DockerFactsWorker({'name': ['my_container'],
                                          'action': 'get_containers'})
        running_containers = get_containers(self.fake_data['containers'])
        self.dfw.client.containers.list.return_value = running_containers
        self.dfw.get_containers()

        self.assertFalse(self.dfw.result['changed'])
        self.assertEqual(self.dfw.client.containers.list.call_count, 1)
        self.assertIn('my_container', self.dfw.result['containers'])
        self.assertDictEqual(
            self.fake_data['containers'][0],
            self.dfw.result['containers']['my_container'])

    def test_get_container_multi(self):
        self.dfw = get_DockerFactsWorker(
            {'name': ['my_container', 'exited_container'],
             'action': 'get_containers'})
        running_containers = get_containers(self.fake_data['containers'])
        self.dfw.client.containers.list.return_value = running_containers
        self.dfw.get_containers()

        self.assertFalse(self.dfw.result['changed'])
        self.assertIn('my_container', self.dfw.result['containers'])
        self.assertNotIn('exited_container', self.dfw.result['containers'])

    def test_get_container_all(self):
        self.dfw = get_DockerFactsWorker({'name': [],
                                          'action': 'get_containers'})
        running_containers = get_containers(self.fake_data['containers'])
        self.dfw.client.containers.list.return_value = running_containers
        self.dfw.get_containers()

        self.assertFalse(self.dfw.result['changed'])
        self.assertIn('my_container', self.dfw.result['containers'])
        self.assertNotIn('exited_container', self.dfw.result['containers'])

    def test_get_containers_env(self):
        fake_env = dict(KOLLA_BASE_DISTRO='ubuntu',
                        KOLLA_INSTALL_TYPE='binary',
                        KOLLA_INSTALL_METATYPE='rdo')
        self.dfw = get_DockerFactsWorker({'name': ['my_container'],
                                          'action': 'get_containers_env'})
        self.fake_data['containers'][0].update(
            self.fake_data['container_inspect'])
        self.dfw.client.containers.get.return_value = construct_container(
            self.fake_data['containers'][0])
        self.dfw.get_containers_env()

        self.assertFalse(self.dfw.result['changed'])
        self.dfw.client.containers.get.assert_called_once_with('my_container')
        self.assertIn('my_container', self.dfw.result['envs'])
        self.assertEquals(self.dfw.result['envs']['my_container'], fake_env)

    def test_get_containers_env_negative(self):
        self.dfw = get_DockerFactsWorker({'name': ['fake_container'],
                                          'action': 'get_containers_env'})
        not_found_exc = docker_error.NotFound("not found")
        self.dfw.client.containers.get = mock.Mock(side_effect=not_found_exc)
        self.dfw.get_containers_env()

        self.assertFalse(self.dfw.result['changed'])
        self.dfw.client.containers.get.assert_called_once_with(
            'fake_container')
        self.dfw.module.fail_json.assert_called_once_with(
            msg="No such container: fake_container")

    def test_get_containers_state(self):
        state = {'Dead': False,
                 'ExitCode': 0,
                 'Pid': 12475,
                 'StartedAt': '2016-06-07T11:22:37.66876269Z',
                 'Status': 'running'}
        self.fake_data['container_inspect'].update({'State': state})
        self.dfw = get_DockerFactsWorker({'name': ['my_container'],
                                          'action': 'get_containers_state'})
        self.fake_data['containers'][0].update({'State': state})
        self.dfw.client.containers.get.return_value = construct_container(
            self.fake_data['containers'][0])
        self.dfw.get_containers_state()

        self.assertFalse(self.dfw.result['changed'])
        self.dfw.client.containers.get.assert_called_once_with('my_container')
        self.assertIn('my_container', self.dfw.result['states'])

    def test_get_containers_state_negative(self):
        self.dfw = get_DockerFactsWorker({'name': ['fake_container'],
                                          'action': 'get_containers_state'})
        not_found_exc = docker_error.NotFound("not found")
        self.dfw.client.containers.get = mock.Mock(side_effect=not_found_exc)
        self.dfw.get_containers_state()

        self.assertFalse(self.dfw.result['changed'])
        self.dfw.client.containers.get.assert_called_once_with(
            'fake_container')
        self.dfw.module.fail_json.assert_called_once_with(
            msg="No such container: fake_container")
