# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import logging
import os
import random
import shlex
import signal
import subprocess
from typing import Dict, Optional

import tenacity
from google.auth.transport import requests

from airflow.providers.google.common.utils.id_token_credentials import get_default_id_token_credentials
from airflow.utils.log.logging_mixin import LoggingMixin

PWD = os.path.dirname(os.path.abspath(__file__))
TERRAFORM_PLAN = os.path.join(PWD, 'iap_terraform_plan')


class _TerraformDeployer(LoggingMixin):
    def __init__(self, terraform_plan, variables: Optional[Dict[str, str]]):
        self.terraform_plan = terraform_plan
        self.variables = variables or {}

    def apply(self):
        env_variable = {f"TF_VAR_{k}": v for k, v in self.variables.items()}
        cmd = ['terraform', 'init', "-input=false"]
        self.log.info("Executing cmd: %s", " ".join(cmd))
        subprocess.check_call(cmd, cwd=self.terraform_plan)
        cmd = ['terraform', 'apply', '-auto-approve', "-input=false"]
        self.log.info("Executing cmd: %s", " ".join(cmd))
        subprocess.check_call(cmd, cwd=self.terraform_plan, env={**os.environ, **env_variable})

    def destroy(self):
        cmd = ['terraform', 'destroy', '-auto-approve', "-input=false"]
        self.log.info("Executing cmd: %s", " ".join(cmd))
        subprocess.check_call(
            cmd,
            cwd=self.terraform_plan,
        )

    def read_output(self, key):
        return (
            subprocess.check_output(['terraform', 'output', '-raw', key], cwd=self.terraform_plan)
            .decode()
            .strip()
        )


class IAPHelper(LoggingMixin):
    def __init__(self, *, client_id, client_secret, region):
        self.client_id = client_id
        self.client_server = client_secret
        self.region = region
        self.deployer = _TerraformDeployer(
            TERRAFORM_PLAN,
            variables={
                'region': region,
                'project_id': os.environ['GCP_PROJECT_ID'],
                'oauth2_client_id': client_id,
                'oauth2_client_secret': client_secret,
            },
        )

    def create_resources(self):
        self.deployer.apply()

    def destroy_resources(self):
        self.deployer.destroy()

    def send_authorized_request(self, path="/", timeout=90):
        id_token = self._get_id_token()
        load_balancer_ip = self.get_load_balancer_ip()
        self.log.info("Sending request: load_balancer_ip=%s, path=%s", load_balancer_ip, path)
        for attempt in tenacity.Retrying(
            stop=tenacity.stop_after_delay(timeout),
            wait=tenacity.wait_exponential(multiplier=1, min=4, max=10),
            retry=tenacity.retry_if_exception_type(subprocess.CalledProcessError),
            after=tenacity.after_log(self.log, logging.INFO),
        ):
            with attempt:
                response = (
                    subprocess.check_output(
                        [
                            'curl',
                            f'https://example.com{path}',
                            '--fail',
                            '--resolve',
                            f"example.com:443:{load_balancer_ip}",
                            '-H',
                            f"Authorization: Bearer {id_token}",
                            '--insecure',
                            '-H',
                            'Content-Type: application/json',
                            '-s',
                        ]
                    )
                    .decode()
                    .strip()
                )
                self.log.info("Response: %s", response)
        return response

    def _get_project_number(self):
        project_id = os.environ['GCP_PROJECT_ID']
        return (
            subprocess.check_output(
                ['gcloud', 'projects', 'describe', project_id, '--format', 'get(projectNumber)']
            )
            .decode()
            .strip()
        )

    def _get_id_token(self):
        self.log.info("Fetching ID Token")
        request_adapter = requests.Request()

        creds = get_default_id_token_credentials(target_audience=self.client_id)
        creds.refresh(request=request_adapter)
        token = creds.token
        return token

    def get_load_balancer_ip(self):
        return self.deployer.read_output('load-balancer-ip')

    def get_mig_name(self):
        return self.deployer.read_output('mig_name')

    def get_backend_service_name(self):
        return self.deployer.read_output('backend_service_name')

    def get_backend_service_name_for_iap(self):
        project_number = self._get_project_number()
        self.log.info("Getting backend service name for IAP")
        backend_service_name = self.get_backend_service_name()
        backend_service_id = (
            subprocess.check_output(
                [
                    'gcloud',
                    'compute',
                    'backend-services',
                    'describe',
                    backend_service_name,
                    '--format=get(id)',
                ]
            )
            .decode()
            .strip()
        )
        name = f'/projects/{project_number}/global/backendServices/{backend_service_id}'
        self.log.info("Backend service name for IAP: %s", name)
        return name

    def get_instance_uri(self):
        return (
            subprocess.check_output(
                [
                    'gcloud',
                    'compute',
                    'instance-groups',
                    'managed',
                    'list-instances',
                    self.get_mig_name(),
                    '--region',
                    self.region,
                    '--format',
                    'get(instance)',
                ]
            )
            .decode()
            .strip()
        )


class CloudSSHRemotePortForwarder(LoggingMixin):
    def __init__(self, instance_uri: str, remote_port: int = 80, local_port: int = 8000):
        self.instance_uri = instance_uri
        self.remote_port = remote_port
        self.local_port = local_port
        self.tunnel: Optional[subprocess.Popen] = None

    def __enter__(self):
        # Install socat
        cmd = [
            'gcloud',
            'compute',
            'ssh',
            self.instance_uri,
            '--tunnel-through-iap',
            '--',
            'sudo',
            'apt',
            'install',
            '-y',
            'socat',
        ]
        self.log.info('Executing cmd: %s', " ".join(shlex.quote(d) for d in cmd))
        subprocess.check_call(cmd)

        # Forward traffic to local environment
        random_port = random.randint(8000, 9000 - 1)
        cmd = [
            'gcloud',
            'compute',
            'ssh',
            self.instance_uri,
            '--tunnel-through-iap',
            '--',
            '-R',
            f'127.0.0.1:{random_port}:127.0.0.1:{self.local_port}',
            'sudo',
            'socat',
            f'tcp-listen:{self.remote_port},reuseaddr,fork',
            f'tcp:localhost:{random_port}',
        ]
        self.log.info('Executing cmd: %s', " ".join(shlex.quote(d) for d in cmd))
        self.tunnel = subprocess.Popen(cmd)
        return self

    def __exit__(self, type, value, traceback):
        if not self.tunnel:
            return
        self.kill_tunnel()
        self.restart_instance()

    def kill_tunnel(self):
        if self.tunnel.poll() is None:
            self.tunnel.send_signal(signal.SIGTERM)
            self.tunnel.wait(10)
            if self.tunnel.poll() is None:
                self.tunnel.kill()

    def restart_instance(self):
        cmd = [
            'gcloud',
            'compute',
            'ssh',
            self.instance_uri,
            '--tunnel-through-iap',
            '--',
            "sudo reboot",
        ]
        self.log.info('Executing cmd: %s', " ".join(shlex.quote(d) for d in cmd))
        subprocess.check_call(cmd)


def forward_remote_port_to_local(instance_uri: str, remote_port: int = 80, local_port: int = 8000):
    return CloudSSHRemotePortForwarder(
        instance_uri=instance_uri, remote_port=remote_port, local_port=local_port
    )
