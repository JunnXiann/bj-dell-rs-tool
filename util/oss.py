#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import oss2


class Oss(object):

    def __init__(self, bucket_host, key_id, key_secret, **kwargs):
        auth = oss2.Auth(key_id, key_secret)
        bucket_name = re.sub(r'http[s]?://', '', bucket_host).split('.')[0]
        oss_host = bucket_host.replace(bucket_name + '.', '')
        self.bucket_host = bucket_host
        self.bucket = oss2.Bucket(auth, oss_host, bucket_name, connect_timeout=10)
        self.readable = self.writeable = None

    def is_readable(self):
        if self.readable is None:
            try:
                self.bucket.list_objects('', max_keys=1)
                self.readable = True
            except Exception as e:
                print('[%s] %s' % (e.__class__.__name__, str(e)))
                self.readable = False
        return self.readable

    def is_writeable(self):
        if self.writeable is None:
            try:
                self.bucket.put_object('1.tmp', '')
                self.bucket.delete_object('1.tmp')
                self.writeable = True
            except Exception as e:
                print('[%s] %s' % (e.__class__.__name__, str(e)))
                self.writeable = False
        return self.writeable

    def download_file(self, oss_file, local_file):
        return self.bucket.get_object_to_file(oss_file, local_file)

    def upload_file(self, oss_file, local_file):
        return self.bucket.put_object_from_file(oss_file, local_file)
