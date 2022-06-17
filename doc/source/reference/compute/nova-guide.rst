======================
Nova - Compute Service
======================

Nova is a core service in OpenStack, and provides compute services. Typically
this is via Virtual Machines (VMs), but may also be via bare metal servers if
Nova is coupled with Ironic.

Nova is enabled by default, but may be disabled by setting ``enable_nova`` to
``no`` in ``globals.yml``.

Virtualisation Drivers
======================

The virtualisation driver may be selected via ``nova_compute_virt_type`` in
``globals.yml``. Supported options are ``qemu``, ``kvm``, and ``vmware``.
The default is ``kvm``.

Libvirt
-------

Information on the libvirt-based drivers ``kvm`` and ``qemu`` can be found in
:doc:`libvirt-guide`.

VMware
------

Information on the VMware-based driver ``vmware`` can be found in
:doc:`vmware-guide`.

Bare Metal
----------

Information on using Nova with Ironic to deploy compute instances to bare metal
can be found in :doc:`../bare-metal/ironic-guide`.

Fake Driver
-----------

The fake driver can be used for testing Nova's scaling properties without
requiring access to a large amount of hardware resources. It is covered in
:doc:`nova-fake-driver`.

.. _nova-consoles:

Consoles
========

The console driver may be selected via ``nova_console`` in ``globals.yml``.
Valid options are ``none``, ``novnc`` and ``spice``. Additionally,
serial console support can be enabled by setting
``enable_nova_serialconsole_proxy`` to ``yes``.

Cells
=====

Information on using Nova Cells V2 to scale out can be found in
:doc:`nova-cells-guide`.

Vendordata
==========

Nova supports passing deployer provided data to instances using a
concept known as Vendordata. If a Vendordata file is located in the
following path within the Kolla configuration, Kolla will
automatically use it when the Nova service is deployed or
reconfigured: ``/etc/kolla/config/nova/vendordata.json``.

Managing resource providers via config files
============================================

In the Victoria cycle Nova merged support for managing resource providers
via `configuration files
<https://docs.openstack.org/nova/latest/admin/managing-resource-providers.html>`__.

Kolla Ansible limits the use of this feature to a single config file per
Nova Compute service, which is defined via Ansible inventory group/host vars.
The reason for doing this is to encourage users to configure each compute
service individually, so that when further resources are added, existing
compute services do not need to be restarted.

For example, a user wanting to configure a compute resource with GPUs for
a specific host may add the following file to host_vars:

.. code-block:: console

    [host_vars]$ cat gpu_compute_0001
    nova_cell_compute_provider_config:
      meta:
        schema_version: '1.0'
      providers:
        - identification:
            name: $COMPUTE_NODE
          inventories:
            additional:
              - CUSTOM_GPU:
                  total: 8
                  reserved: 0
                  min_unit: 1
                  max_unit: 1
                  step_size: 1
                  allocation_ratio: 1.0

A similar approach can be used with group vars to cover more than one machine.

Since a badly formatted file will prevent the Nova Compute service from
starting, it should first be validated as described in the `documentation
<https://docs.openstack.org/nova/latest/admin/managing-resource-providers.html>`__.
The Nova Compute service can then be reconfigured to apply the change.

To remove the resource provider configuration, it is simplest to leave the
group/host vars in place without specifying any inventory or traits. This will
effectively remove the configuration when the Nova Compute service is restarted.
