#!/bin/bash -e

#copy configs into neutron_server container
#python3 roles/neutron/files/render.py < roles/neutron/templates/ContrailPlugin.ini.j2 > roles/neutron/files/ContrailPlugin.ini
sudo docker cp /tmp/ContrailPlugin.ini neutron_server:/etc/neutron/
sudo docker cp /tmp/api-paste.ini neutron_server:/etc/neutron/
sudo docker cp /tmp/contrail-plugin.pth neutron_server:/usr/lib/python3.6/site-packages/

#change configs in /etc/kolla
if grep -q "command" /etc/kolla/neutron-server/config.json; then
    sed -ri 's/"command".*//' /etc/kolla/neutron-server/config.json
fi

if  !(grep -q "neutron-server --config-file /etc/neutron/neutron.conf --config-file /etc/neutron/ContrailPlugin.ini --config-file /etc/neutron/api-paste.ini" /etc/kolla/neutron-server/config.json); then
    sed -i '2i\"command\": \"neutron-server --config-file /etc/neutron/neutron.conf --config-file /etc/neutron/ContrailPlugin.ini --config-file /etc/neutron/api-paste.ini\",' /etc/kolla/neutron-server/config.json
fi

if  !(grep -q "core_plugin = neutron_plugin_contrail.plugins.opencontrail.contrail_plugin.NeutronPluginContrailCoreV2" /etc/kolla/neutron-server/neutron.conf); then
    sed -i 's/core_plugin =.*/core_plugin = neutron_plugin_contrail.plugins.opencontrail.contrail_plugin.NeutronPluginContrailCoreV2/' /etc/kolla/neutron-server/neutron.conf
fi

if !(grep -q "api_paste_config = /etc/neutron/api-paste.ini" /etc/kolla/neutron-server/neutron.conf); then
    sed -i 's/api_paste_config =.*/api_paste_config = /etc/neutron/api-paste.ini' /etc/kolla/neutron-server/neutron.conf
fi

if  !(grep -q "metadata_proxy_socket" /etc/kolla/neutron-server/neutron.conf); then
    sed -i '2a metadata_proxy_socket = /var/lib/neutron/kolla/metadata_proxy' /etc/kolla/neutron-server/neutron.conf
fi

if  !(grep -q "allow_overlapping_ips" /etc/kolla/neutron-server/neutron.conf); then
    sed -i '3a allow_overlapping_ips = true' /etc/kolla/neutron-server/neutron.conf
fi

if  grep -q "interface_driver = openvswitch" /etc/kolla/neutron-server/neutron.conf; then
    sed -ri 's/interface_driver = openvswitch//' /etc/kolla/neutron-server/neutron.conf
fi

if  !(grep -q "service_plugins = contrail-tags" /etc/kolla/neutron-server/neutron.conf); then
    sed -i 's/service_plugins =.*/service_plugins = contrail-tags,/' /etc/kolla/neutron-server/neutron.conf
fi

if  !(grep -q "api_extensions_path" /etc/kolla/neutron-server/neutron.conf); then
    sed -i '/[DEFAULT]/a api_extensions_path = /opt/plugin/site-packages/neutron_plugin_contrail/extensions:/opt/plugin/site-packages/neutron_lbaas/extensions' /etc/kolla/neutron-server/neutron.conf
fi

if  grep -q "connection_recycle_time = 10" /etc/kolla/neutron-server/neutron.conf; then
    sed -ri 's/connection_recycle_time = 10//' /etc/kolla/neutron-server/neutron.conf
fi

if  grep -q "max_pool_size = 1" /etc/kolla/neutron-server/neutron.conf; then
    sed -ri 's/max_pool_size = 1//' /etc/kolla/neutron-server/neutron.conf
fi

if  !(grep -q "password = contrail123" /etc/kolla/neutron-server/neutron.conf); then
    sed -i 's/password =.*/:password = contrail123' /etc/kolla/neutron-server/neutron.conf
fi

if  !(grep -q "memcache_secret_key = contrail123" /etc/kolla/neutron-server/neutron.conf); then
    sed -i 's/memcache_secret_key =.*/memcache_secret_key = contrail123' /etc/kolla/neutron-server/neutron.conf
fi

echo \[quotas]\ >> /etc/kolla/neutron-server/neutron.conf

echo \quota_network=-1\ >> /etc/kolla/neutron-server/neutron.conf

echo \quota_subnet=-1\ >> /etc/kolla/neutron-server/neutron.conf

echo \quota_port=-1\ >> /etc/kolla/neutron-server/neutron.conf

echo \quota_driver=neutron_plugin_contrail.plugins.opencontrail.quota.driver.QuotaDriver\ >> /etc/kolla/neutron-server/neutron.conf

