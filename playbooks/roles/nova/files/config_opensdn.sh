#!/bin/bash -e

sudo docker cp nova_compute:/etc/nova/rootwrap.conf /tmp/
sed -i '/exec_dirs/ s/$/,\/opt\/plugin\/bin /' /tmp/rootwrap.conf
sudo docker cp /tmp/rootwrap.conf nova_compute:/etc/nova/
sudo docker cp /tmp/contrail-plugin.pth nova_compute:/usr/lib/python3.9/site-packages/
#if !(grep -q "nova-compute --config-file /etc/nova/nova.conf --config-file /etc/nova/rootwrap.conf\"); then
sed -ri 's/"command".*//' /etc/kolla/nova-compute/config.json
sed -i '2i\"command\": \"nova-compute --config-file /etc/nova/nova.conf --config-file /etc/nova/rootwrap.conf\",' /etc/kolla/nova-compute/config.json
if !(grep -q "scheduler_default_filters = RetryFilter, AvailabilityZoneFilter, RamFilter, ComputeFilter, ComputeCapabilitiesFilter, ImagePropertiesFilter, PciPassthroughFilter" /etc/kolla/nova-compute/  nova.conf); then
    sed -i '2a scheduler_default_filters = RetryFilter, AvailabilityZoneFilter, RamFilter, ComputeFilter, ComputeCapabilitiesFilter, ImagePropertiesFilter, PciPassthroughFilter' /etc/kolla/nova-compute/nova.conf
fi

if !(grep -q "scheduler_available_filters = nova.scheduler.filters.all_filters" /etc/kolla/nova-compute/nova.conf); then
    sed -i '3a scheduler_available_filters = nova.scheduler.filters.all_filters' /etc/kolla/nova-compute/nova.conf
fi

for nova_conf in /etc/kolla/nova-api/nova.conf \
                 /etc/kolla/nova-compute/nova.conf \
                 /etc/kolla/nova-conductor/nova.conf \
                 /etc/kolla/nova-scheduler/nova.conf
do
    echo \[oslo_policy]\ >> "$nova_conf"
    echo enforce_new_defaults = False >> "$nova_conf"
    echo enforce_scope = False >> "$nova_conf"
done
