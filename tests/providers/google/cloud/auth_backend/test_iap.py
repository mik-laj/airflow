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

import os
import shlex
import subprocess
import unittest
from tempfile import TemporaryDirectory

from airflow.utils.log.logging_mixin import LoggingMixin
from tests.test_utils.iap_helper import IAPHelper, forward_remote_port_to_local

OAUTH_CLIENT_ID = os.environ.get('GCP_IAP_OAUTH_CLIENT_ID')
OAUTH_CLIENT_SECRET = os.environ.get('GCP_IAP_OAUTH_CLIENT_SECRET')
REGION = os.environ.get('GCP_IAP_REGION', 'us-east1')
# When set to "true" resources will not be deleted or created by Terraform.
SKIP_TERRAFORM = os.environ.get('SKIP_TERRAFORM', 'false')


class TestIdentityAwareProxy(unittest.TestCase, LoggingMixin):
    def setUp(self) -> None:
        self.helper = IAPHelper(client_id=OAUTH_CLIENT_ID, client_secret=OAUTH_CLIENT_SECRET, region=REGION)
        if SKIP_TERRAFORM != 'true':
            self.helper.create_resources()

    def tearDown(self) -> None:
        if SKIP_TERRAFORM != 'true':
            self.helper.destroy_resources()

    def test_should_connect_identity_aware(self):
        self.log.info("Load balancer IP: %s", self.helper.get_load_balancer_ip())
        self.log.info("Mig Name: %s", self.helper.get_mig_name())
        instance_uri = self.helper.get_instance_uri()
        self.log.info("Instance URI: %s", instance_uri)

        response = self.helper.send_authorized_request(timeout=20 * 60)
        assert "Hello" in response

        # Kill webserver
        cmd = [
            'gcloud',
            'compute',
            'ssh',
            instance_uri,
            '--tunnel-through-iap',
            '--',
            "sudo pkill -f 'python3 -m http.server'",
        ]
        self.log.info('Executing cmd: %s', " ".join(shlex.quote(d) for d in cmd))
        subprocess.check_call(cmd)

        with forward_remote_port_to_local(instance_uri=instance_uri):
            with TemporaryDirectory() as tmp_dir:
                with open(os.path.join(tmp_dir, "index.html"), "w+") as index_file:
                    index_file.write("System tests")
                proc = subprocess.Popen(["python", "-m", "http.server", "8000"], cwd=tmp_dir)
                response = self.helper.send_authorized_request()
                assert "System tests" in response
                proc.terminate()
                proc.wait()
