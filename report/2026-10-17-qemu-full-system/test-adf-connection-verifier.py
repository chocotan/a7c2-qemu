#!/usr/bin/env python3
"""C-produced third-edge records; predecessor and DTB are explicit host mocks."""
from pathlib import Path
import runpy
import unittest


class ThirdEdgeEvidence(runpy.run_path(str(Path(__file__).with_name('test-scalar-connection-verifier.py')))['SecondEdgeEvidence']):
    family='ADF'
    profile='adf_connection'
    producer_test='test-adf-connection.c'
    producer_env='ADF_CONNECTION_HOST_FIXTURE'
    predecessor='verify-adf-pin.py'
    proof_key='adf_control_connection_verified'
    next_key='next_type4_out0_get_free_verified'
    next_slot=7
    token='fullsystem.adf-connect=control'


if __name__=='__main__':unittest.main()
