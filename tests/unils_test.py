# -*- coding: utf-8 -*-
#
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

import unittest
import os

import six
from urllib.parse import urlparse


def _id(obj):
    return obj


def skipOtherDatabaseEngine(wanted_db_engines):
    """
    Skip a test is if the specific database engine is not used
    """
    wanted_db_engines = ['sqlite'] \
        if wanted_db_engines is None else wanted_db_engines
    wanted_db_engines = [wanted_db_engines] \
        if isinstance(wanted_db_engines, six.string_types) is None \
        else wanted_db_engines

    if 'AIRFLOW__CORE__SQL_ALCHEMY_CONN' not in os.environ:
        return _id

    conn_url = os.environ['AIRFLOW__CORE__SQL_ALCHEMY_CONN']
    if not conn_url:
        return _id

    current_db_engine = urlparse(conn_url).scheme

    if current_db_engine in wanted_db_engines:
        return unittest.skip("This test is run only on: %s" % wanted_db_engines)
    return _id
