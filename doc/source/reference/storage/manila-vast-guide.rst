.. _manila-vast-guide:

==========================================================
VAST Manila Driver for OpenStack
==========================================================

VAST Share Driver integrates OpenStack with VAST Data's Storage System.
Shares in the Shared File System service are mapped to directories
on VAST, and are accessed via NFS protocol using a Virtual IP Pool.

For more details on how to use the VAST driver, refer to the
`VAST share driver docs <https://docs.openstack.org/manila/latest/configuration/shared-file-systems/drivers/vastdata_driver.html>`_.

Configuration on Kolla deployment
---------------------------------

Enable Manila and the VAST driver in ``/etc/kolla/globals.yml``:

.. code-block:: yaml

   enable_manila: "yes"
   enable_manila_backend_vast: "yes"

In ``/etc/kolla/globals.yml`` uncomment and set:

.. code-block:: yaml

   manila_vast_mgmt_host: "<hostname or IP for VAST REST API>"
   manila_vast_mgmt_user: "<username>"
   vast_mgmt_password: "<password>"
   manila_vast_vippool_name: "<virtual IP pool name>"

The driver assumes tenant networks that which to mount
their VAST backed NFS file shares are able to route to the
VAST virtual IP pool you have chosen.
By default, the driver will create shares under
``/manila`` base export on VAST.
