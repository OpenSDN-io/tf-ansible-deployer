#!/bin/bash -e

echo \[oslo_policy]\ >> /etc/kolla/glance-api/glance-api.conf

echo enforce_new_defaults = False >> /etc/kolla/glance-api/glance-api.conf

echo enforce_scope = False >> /etc/kolla/glance-api/glance-api.conf
