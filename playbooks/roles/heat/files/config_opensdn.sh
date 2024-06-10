#!/bin/bash -e

sudo docker cp /tmp/contrail-plugin.pth heat_engine:/usr/lib/python3.6/site-packages/
if !(grep -q "plugin_dirs = /opt/plugin/site-packages/vnc_api/gen/heat/resources,/opt/plugin/site-packages/contrail_heat/resources" /etc/kolla/heat-engine/heat.conf); then
    sed -i '2a plugin_dirs = /opt/plugin/site-packages/vnc_api/gen/heat/resources,/opt/plugin/site-packages/contrail_heat/resources' /etc/kolla/heat-engine/heat.conf
fi
