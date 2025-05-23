#!/usr/bin/env python3


"""
This filter plugin script takes api_server_list and instances file as input and
returns lists of new roles, existing roles, deleted roles and instances roles
for all the nodes in the instances file.
"""

import requests
import json


class FilterModule(object):

    # OpenstackCluster object
    os_roles = None

    # ContrailCluster object
    opensdn_roles = None

    indexed_roles = [
        'toragent',
    ]

    def filters(self):
        return {
            'calculate_openstack_roles': self.calculate_openstack_roles,
            'calculate_opensdn_roles': self.calculate_opensdn_roles,
            'extract_roles': self.extract_roles,
            'calculate_deleted_toragent_roles': self.calculate_deleted_toragent_roles
        }

    def calculate_openstack_roles(self, existing_dict, instances_dict, global_configuration,
                                  contrail_configuration, kolla_config, hostvars):
        # don't calculate anything if global_configuration.ENABLE_DESTROY is not set
        empty_result = {"node_roles_dict": dict(),
                        "deleted_nodes_dict": dict()}
        enable_destroy = global_configuration.get("ENABLE_DESTROY", True)
        if not isinstance(enable_destroy, bool):
            enable_destroy = str(enable_destroy).lower() == 'true'
        if not enable_destroy:
            return str(empty_result)

        self.os_roles = OpenstackCluster(instances_dict, contrail_configuration, kolla_config)
        instances, deleted_nodes_dict = self.os_roles.discover_openstack_roles(hostvars)

        return str({"node_roles_dict": instances,
                    "deleted_nodes_dict": deleted_nodes_dict})

    def calculate_opensdn_roles(self, existing_dict, api_server_list,
                                instances_dict, global_configuration,
                                contrail_configuration, kolla_config, hostvars):
        # don't calculate anything if global_configuration.ENABLE_DESTROY is not set
        empty_result = {"node_roles_dict": dict(),
                        "deleted_nodes_dict": dict(),
                        "api_server_ip": None}
        enable_destroy = global_configuration.get("ENABLE_DESTROY", True)
        if not isinstance(enable_destroy, bool):
            enable_destroy = str(enable_destroy).lower() == 'true'
        if not enable_destroy:
            return str(empty_result)

        self.opensdn_roles = ContrailCluster(
            instances_dict, contrail_configuration, kolla_config)
        instances, deleted_nodes_dict, api_server_ip = self.opensdn_roles.discover_opensdn_roles()

        return str({"node_roles_dict": instances,
                    "deleted_nodes_dict": deleted_nodes_dict,
                    "api_server_ip": api_server_ip})

    def extract_roles(self, existing_roles, instance_data):
        existing_roles[instance_data["key"]] = dict()
        if not instance_data["value"]["roles"]:
            return existing_roles

        for role, data in instance_data["value"]["roles"].items():
            ix_name = next((s for s in self.indexed_roles if s in role), None)
            if not ix_name:
                existing_roles[instance_data["key"]][role] = data
            else:
                # indexed role name must be equal to pattern ROLENAME_INDEX
                index = role[len(ix_name) + 1:]
                if index:
                    existing_roles[instance_data["key"]].setdefault(ix_name, dict())[index] = data

        return existing_roles

    def calculate_deleted_toragent_roles(self, cluster_roles_dict, instance_data):
        node_roles_dict = cluster_roles_dict['node_roles_dict']
        deleted_nodes_dict = cluster_roles_dict['deleted_nodes_dict']
        instance_roles = []
        if instance_data["value"]["roles"]:
            instance_roles = set(instance_data["value"]["roles"].keys())

        for role in node_roles_dict[instance_data['key']]['existing_roles']:
            if isinstance(role, dict):
                for key, value in role.items():
                    if key not in instance_roles:
                        node_roles_dict[instance_data['key']]['deleted_roles'].append(role)

        return str({"node_roles_dict": node_roles_dict,
                    "deleted_nodes_dict": deleted_nodes_dict,
                    "api_server_ip": cluster_roles_dict["api_server_ip"]})


class OpenstackCluster(object):
    # OpenStackParams object
    os_params = None

    node_name_ip_map = {}
    node_ip_name_map = {}
    valid_roles = [
        "openstack_control", "openstack_network", "openstack_storage",
        "openstack_monitoring", "openstack_compute", "openstack"
    ]

    def __init__(self, instances, contrail_configuration, kolla_config):
        # Initialize the openstack params
        self.os_params = OpenStackParams(contrail_configuration, kolla_config)
        self.instances_dict = instances

    def discover_openstack_roles(self, hostvars):
        instances = {}
        deleted_nodes_dict = {}

        for instance_name, instance_config in self.instances_dict.items():
            instances[instance_name] = {}
            self.node_name_ip_map[instance_name] = instance_config["ip"]
            self.node_ip_name_map[instance_config["ip"]] = instance_name
            if "roles" in instance_config \
                    and isinstance(instance_config["roles"], dict):
                instances[instance_name]['instance_roles'] = \
                    list(
                        set(
                            instance_config["roles"].keys()
                        ).intersection(set(self.valid_roles)))

        try:
            instances, deleted_nodes_dict = \
                self.discover_openstack_computes(instances, deleted_nodes_dict, hostvars)
        except Exception:
            # either services are not installed yet or they are broken
            return dict(), dict()

        for server in instances:
            for role_list, list_of_roles in \
                    instances[server].items():
                if len(list_of_roles) and "openstack" in list_of_roles:
                    list_of_roles.remove("openstack")
                    list_of_roles += self.os_params.openstack_controller_roles
                    instances[server][role_list] = list_of_roles

            if "instance_roles" not in instances[server]:
                instances[server]['instance_roles'] = []
            if "existing_roles" not in instances[server]:
                instances[server]['existing_roles'] = []
            else:
                instances[server]['existing_roles'] =\
                    list(set(instances[server]['existing_roles']))

            instances[server]['new_roles'] = list(set(
                instances[server]['instance_roles']
            ).difference(
                set(instances[server]['existing_roles'])
            ))
            instances[server]['deleted_roles'] = list(set(
                instances[server]['existing_roles']
            ).difference(
                set(instances[server]['instance_roles'])
            ))

            if len(instances[server]['deleted_roles']) and\
                    (instances[server]['deleted_roles'] ==
                        instances[server]['existing_roles']):
                deleted_nodes_dict[server] = self.node_name_ip_map[server]

        self.node_roles_dict = instances
        self.deleted_nodes_dict = deleted_nodes_dict
        return instances, deleted_nodes_dict

    def get_ops_hostname(self, ip_address):
        return "fqdn"

    # node_ip_name_map containes ip address to host name mappings built from the
    # instances dict. service_ip could be either ctrl-data or mgmt (that is
    # given under 'ip' field of the instances entry. This function goes through
    # all the IP addresses for a host and if an address matching the IP is
    # found, then the corresponding mgmt ip is used to index into the
    # node_ip_name_map dict to get the server name
    def get_instance_name(self, service_ip, hostvars):
        for i in hostvars:
            if service_ip in hostvars[i].get('ansible_all_ipv4_addresses', []):
                for ip in hostvars[i]['ansible_all_ipv4_addresses']:
                    if ip in self.node_ip_name_map:
                        return ip, self.node_ip_name_map[ip]
        return service_ip, None

    def discover_openstack_computes(self, instances, deleted_nodes_dict, hostvars):
        # Read Openstack Computes
        response = self.os_params.get_os_hypervisors().json()
        if "hypervisors" not in response:
            return instances, deleted_nodes_dict

        for hyp in response["hypervisors"]:
            server_ip, server_name = self.get_instance_name(hyp["host_ip"], hostvars)
            if server_name:
                if "existing_roles" not in instances[server_name]:
                    instances[server_name]['existing_roles'] = []
                instances[server_name]['existing_roles'].append("openstack_compute")
            else:
                hostname = hyp["hypervisor_hostname"].split('.')[0]
                deleted_nodes_dict[hostname] = self.instances_dict[hostname]['ip']

        return instances, deleted_nodes_dict

    def discover_openstack_controllers(self, instances, deleted_nodes_dict):
        # Read Openstack Controllers
        response = self.os_params.get_os_endpoints().json()
        if "endpoints" not in response:
            return instances, deleted_nodes_dict

        for endpoint in response["endpoints"]:
            ip, port = endpoint["url"].split('://')[1].split('/')[0].split(':')
            if port not in self.os_params.endpoint_port_role_map:
                continue

            openstack_role = "openstack_" + self.os_params.endpoint_port_role_map[port]
            if ip in self.node_ip_name_map:
                server_name = self.node_ip_name_map[ip]
                if "existing_roles" not \
                        in instances[server_name]:
                    instances[server_name][
                        'existing_roles'] = []
                instances[server_name][
                    'existing_roles'].append(openstack_role)
            else:
                # TODO: Implement
                deleted_server_name = self.get_ops_hostname(ip)
                deleted_nodes_dict[deleted_server_name] = ip
        return instances, deleted_nodes_dict


# class that handles parameters required to talk to openstack and detect
# existing roles
class OpenStackParams(object):

    DEFAULT_KEYSTONE_AUTH_PORT = "5000"

    # static params
    endpoint_port_role_map = {
        DEFAULT_KEYSTONE_AUTH_PORT: "control",
        "9696": "network",
        "8776": "storage",
        "3000": "monitoring",
        "8774": "compute"
    }

    ks_auth_url_endpoint_dict = {
        "/v3": "/auth/tokens",
        "/v2.0": "/tokens"
    }

    openstack_controller_roles = [
        "openstack_control", "openstack_network", "openstack_storage",
        "openstack_monitoring"
    ]

    # Non-static data
    ks_auth_headers = {
        'Content-Type': 'application/json'
    }

    ks_auth_url = None
    os_hypervisors_url = None
    os_endpoints_url = None

    ks_auth_host = None
    ks_admin_password = ""
    ks_admin_tenant = ""
    ks_admin_user = ""
    ks_auth_url_version = "/v3"  # default for openstack queens is "/v3"
    ks_auth_proto = "http"
    auth_token = None
    aaa_mode = None

    def __init__(self, contrail_config, kolla_config):
        self.ks_auth_host = contrail_config.get("KEYSTONE_AUTH_HOST", None)
        if kolla_config is not None and kolla_config.get("kolla_globals"):
            self.ks_auth_host = kolla_config["kolla_globals"].get(
                "kolla_external_vip_address",
                self.ks_auth_host)
            if kolla_config["kolla_globals"].get("kolla_enable_tls_external", None):
                self.ks_auth_proto = "https"
        self.ks_admin_user = contrail_config.get(
            "KEYSTONE_AUTH_ADMIN_USER", "admin")
        self.ks_admin_password = contrail_config.get(
            "KEYSTONE_AUTH_ADMIN_PASSWORD", "contrail123")
        self.ks_admin_tenant = contrail_config.get(
            "KEYSTONE_AUTH_ADMIN_TENANT", "admin")
        self.ks_auth_url_version = contrail_config.get(
            "KEYSTONE_AUTH_URL_VERSION", "/v3")
        self.ks_auth_public_port = contrail_config.get(
            "KEYSTONE_AUTH_PUBLIC_PORT", self.DEFAULT_KEYSTONE_AUTH_PORT)
        ks_tokens_url = self.ks_auth_url_endpoint_dict.get(
            self.ks_auth_url_version)
        if not ks_tokens_url:
            raise Exception("Unknown keystone auth version {}".format(self.ks_auth_url_version))

        if self.ks_auth_public_port != self.DEFAULT_KEYSTONE_AUTH_PORT:
            value = self.endpoint_port_role_map.pop(self.DEFAULT_KEYSTONE_AUTH_PORT)
            self.endpoint_port_role_map[self.ks_auth_public_port] = value

        if self.ks_auth_host:
            base_url = "{}://{}:{}{}".format(
                self.ks_auth_proto, self.ks_auth_host, self.ks_auth_public_port,
                self.ks_auth_url_version)
            self.ks_auth_url = base_url + ks_tokens_url
            self.os_endpoints_url = base_url + '/endpoints'
            self.os_hypervisors_url = "{}://{}:8774/v2.1/os-hypervisors/detail".format(
                self.ks_auth_proto, self.ks_auth_host)

        if contrail_config.get("CLOUD_ORCHESTRATOR") == "openstack":
            self.get_ks_auth_token(contrail_config)
            self.aaa_mode = contrail_config.get("AAA_MODE", None)
        # TODO: Implement other Auth methods

    def get_ks_token_request(self):
        keystone_token_request = {
            'auth': {
                'identity': {
                    'methods': [
                        'password'
                    ],
                    'password': {
                        'user': {
                            'domain': {
                                'id': 'default'
                            },
                            'name': self.ks_admin_user,
                            'password': self.ks_admin_password
                        }
                    }
                },
                'scope': {
                    'project': {
                        'domain': {
                            'name': 'default'
                        },
                        'name': self.ks_admin_tenant
                    }
                }
            }
        }

        return keystone_token_request

    def get_ks_auth_token(self, contrail_config):
        try:
            response = self.get_rest_api_response(
                self.ks_auth_url,
                self.ks_auth_headers,
                data=json.dumps(self.get_ks_token_request()),
                request_type="post")
        except Exception:
            self.auth_token = None
        else:
            header = response.headers
            self.auth_token = header['X-Subject-Token']
            if self.aaa_mode != "no-auth":
                self.ks_auth_headers['X-Auth-Token'] = self.auth_token

            try:
                # Check if endpoint URL is also reachable
                # To protect against re-run after failed provision
                self.get_os_endpoints()
            except Exception:
                self.auth_token = None

    def get_rest_api_response(self, url, headers, data=None, request_type=None):
        response = None
        if request_type == "post":
            response = requests.post(url, headers=headers, data=data)
        elif request_type == "get":
            response = requests.get(url, headers=headers, data=data)
        response.raise_for_status()
        return response

    def get_os_hypervisors(self):
        return self.get_rest_api_response(
            self.os_hypervisors_url,
            self.ks_auth_headers,
            request_type="get")

    def get_os_endpoints(self):
        return self.get_rest_api_response(
            self.os_endpoints_url,
            self.ks_auth_headers,
            request_type="get")


class ContrailCluster(object):

    api_server_port = "8082"
    os_params = None
    instances_dict = {}
    cc_dict = {}
    kolla_dict = {}
    node_name_ip_map = {}
    node_ip_name_map = {}
    existing_tor_agents = {}
    proto = 'http'

    contrail_object_map = {
        # FIXME: Currently we support add/delete of only vrouter nodes. When
        #        adding support for add/del of other roles, this should be uncommented
        #        and look up the ip_role_map only for objects that have 'router_type'
        #        set to 'control_node' and ignore other 'bgp-routers' objects
        # "config-nodes": "config",
        # "database-nodes": "analytics_database",
        # "bgp-routers": "control",
        # "analytics-nodes": "analytics",
        # "analytics-alarm-nodes": "analytics_alarm",
        # "analytics-snmp-nodes": "analytics_snmp",
        "virtual-routers": "vrouter"
    }

    ip_role_map = {
        "virtual-routers": "virtual_router_ip_address",
        "config-nodes": "config_node_ip_address",
        "database-nodes": "database_node_ip_address",
        "bgp-routers": "bgp_router_parameters.address",
        "analytics-nodes": "analytics_node_ip_address",
        "analytics-alarm-nodes": "analytics_alarm_node_ip_address",
        "analytics-snmp-nodes": "analytics_snmp_node_ip_address"
    }

    valid_roles = ["config", "control", "analytics_database",
                   "analytics", "analytics_alarm", "analytics_snmp", "vrouter"]

    def __init__(self, instances, contrail_config, kolla_config):
        self.os_params = OpenStackParams(contrail_config, kolla_config)
        self.instances_dict = instances
        self.cc_dict = contrail_config
        self.kolla_dict = kolla_config
        sslenable = contrail_config.get('SSL_ENABLE', False)
        if str(sslenable) in ['True', 'TRUE', 'yes', 'YES', 'Yes']:
            self.proto = 'https'

    def get_rest_api_response(self, url, headers, data=None, request_type=None):
        response = None
        if request_type == "post":
            response = requests.post(url, headers=headers, data=data)
        elif request_type == "get":
            response = requests.get(url, headers=headers, data=data, verify=False)
        response.raise_for_status()
        return response

    def calculate_valid_api_server_ip(self, api_server_list):
        for test_ip in api_server_list:
            test_url = "{}://{}:{}".format(self.proto, test_ip, self.api_server_port)
            try:
                self.get_rest_api_response(
                    test_url,
                    headers=self.os_params.ks_auth_headers,
                    request_type="get")
                return test_ip
            except Exception:
                pass

        return None

    def get_ip_for_contrail_node(self, instance_name, uuid, contrail_object,
                                 url, headers):
        node_url = url + str(contrail_object[:-1]) + "/" + str(uuid)
        response = self.get_rest_api_response(node_url,
                                              self.os_params.ks_auth_headers,
                                              request_type="get")
        node_object_dict = response.json()
        node_object_dict = node_object_dict[contrail_object[:-1]]
        if "." in self.ip_role_map[contrail_object]:
            key = str(self.ip_role_map[contrail_object]).split('.')[0]
            second_key = str(self.ip_role_map[contrail_object]).split('.')[1]
        else:
            key = str(self.ip_role_map[contrail_object])
            second_key = None

        ip = node_object_dict[key]
        if second_key:
            ip = ip[second_key]
        return ip

    def discover_contrail_cluster(self, instances, deleted_nodes_dict):
        self.contrail_api_url = "{}://{}:{}/".format(self.proto, self.api_server_ip, self.api_server_port)

        for contrail_object, contrail_role in self.contrail_object_map.items():
            contrail_object_url = self.contrail_api_url + str(contrail_object)
            response = self.get_rest_api_response(contrail_object_url,
                                                  self.os_params.ks_auth_headers,
                                                  request_type="get")
            object_dict = response.json()
            object_list = object_dict[contrail_object]
            vr_obj_list = []
            if contrail_role == 'vrouter':
                for vr_obj in object_list:
                    vr_href = vr_obj.get('href')
                    response = self.get_rest_api_response(
                        vr_href,
                        self.os_params.ks_auth_headers,
                        request_type="get")
                    vr_object_dict = response.json()
                    vr_dict = vr_object_dict.get('virtual-router')
                    vr_type = vr_dict.get('virtual_router_type')
                    if vr_type != 'tor-agent':
                        vr_obj_list.append(vr_obj)
                        continue

                    tor_config = {}
                    toragent_fq_name = vr_dict.get('fq_name')[-1]
                    toragent_ip = vr_dict.get('virtual_router_ip_address')
                    pr_href = vr_dict['physical_router_back_refs'][0].get('href')
                    response = self.get_rest_api_response(
                        pr_href,
                        self.os_params.ks_auth_headers,
                        request_type="get")
                    pr_object_dict = response.json()
                    pr_name = pr_object_dict['physical-router']['name']
                    pr_vendor = pr_object_dict['physical-router']['physical_router_vendor_name']
                    tor_config['tor_name'] = pr_name
                    tor_config['pr_vendor'] = pr_vendor
                    tor_config['toragent_ip'] = toragent_ip
                    self.existing_tor_agents[toragent_fq_name] = tor_config

                object_list = vr_obj_list

            for object_to_process in object_list:
                if len(object_to_process.get("fq_name", [])) < 2:
                    continue
                instance_name = str(object_to_process.get("fq_name")[-1])
                fq_name = instance_name
                if '.' in instance_name:
                    instance_name = instance_name.split('.')[0]
                uuid = str(object_to_process.get("uuid"))
                ip_address = self.get_ip_for_contrail_node(
                    instance_name,
                    uuid,
                    contrail_object,
                    self.contrail_api_url,
                    self.os_params.ks_auth_headers)

                # Check if this is a deleted instance
                # Either not in instances.yml or has empty role list in instances
                if instance_name not in instances:
                    instances[instance_name] = {}
                    deleted_nodes_dict[fq_name] = ip_address
                elif 'instance_roles' not in instances[
                    instance_name] or \
                        not len(instances[instance_name]['instance_roles']):
                    if instance_name not in deleted_nodes_dict and \
                            self.node_name_ip_map.get(instance_name, None):
                        deleted_nodes_dict[fq_name] = \
                            self.node_name_ip_map[instance_name]

                if 'existing_roles' not in instances[instance_name]:
                    instances[instance_name]['existing_roles'] = list()
                instances[instance_name]['existing_roles'].append(contrail_role)

        return instances, deleted_nodes_dict

    def discover_opensdn_roles(self):
        instances = {}
        deleted_nodes_dict = {}
        cluster_role_set = set()

        instances_dict = self.instances_dict
        contrail_configuration = self.cc_dict
        for instance_name, instance_config in instances_dict.items():
            instances[instance_name] = {}
            self.node_name_ip_map[instance_name] = instance_config["ip"]
            self.node_ip_name_map[instance_config["ip"]] = instance_name
            if "roles" in instance_config \
                    and isinstance(instance_config["roles"], dict):
                instances[instance_name]['instance_roles'] = \
                    list(
                        set(
                            instance_config["roles"].keys()
                        ).intersection(set(self.valid_roles)))
                cluster_role_set.update(instance_config["roles"].keys())

        # Check if Controller Nodes was given
        if contrail_configuration.get('CONFIG_NODES', None):
            controller_node_list = contrail_configuration.get(
                'CONFIG_NODES').split(',')
        elif contrail_configuration.get('CONTROLLER_NODES', None):
            controller_node_list = contrail_configuration.get(
                'CONTROLLER_NODES').split(',')
        else:
            controller_node_list = None
        if isinstance(controller_node_list, list) and \
                len(controller_node_list):
            api_server_list = controller_node_list
        else:
            api_server_list = []

        if contrail_configuration.get('CONFIG_API_PORT', None):
            self.api_server_port = contrail_configuration.get('CONFIG_API_PORT')

        self.api_server_ip = self.calculate_valid_api_server_ip(api_server_list)

        if self.api_server_ip:
            instances, deleted_nodes_dict = \
                self.discover_contrail_cluster(
                    instances, deleted_nodes_dict)

        for server in instances:
            if "instance_roles" not in instances[server]:
                instances[server]['instance_roles'] = []
            if "existing_roles" not in instances[server]:
                instances[server]['existing_roles'] = []
            instances[server]['new_roles'] = list(set(
                instances[server]['instance_roles']
            ).difference(
                set(instances[server]['existing_roles'])
            ))
            instances[server]['deleted_roles'] = list(set(
                instances[server]['existing_roles']
            ).difference(
                set(instances[server]['instance_roles'])
            ))

        if self.existing_tor_agents:
            for toragent in self.existing_tor_agents:
                server = toragent.split('-')[0]
                tor_agent_id = toragent.split('-')[-1]
                toragent_roles = {}
                toragent_roles[('toragent_' + str(tor_agent_id))] = self.existing_tor_agents[toragent]
                if server in instances:
                    instances[server]['existing_roles'].append(toragent_roles)
                elif server not in deleted_nodes_dict:
                    deleted_nodes_dict[server] = self.existing_tor_agents[toragent]['toragent_ip']

        return instances, deleted_nodes_dict, self.api_server_ip
