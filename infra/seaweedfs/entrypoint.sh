#!/bin/sh
# Render the S3 identity file from env (no credentials in the repo), then start SeaweedFS.
set -eu
cat > /tmp/s3.json <<JSON
{"identities":[{"name":"ksei","credentials":[{"accessKey":"${S3_ACCESS_KEY}","secretKey":"${S3_SECRET_KEY}"}],"actions":["Admin","Read","Write","List","Tagging"]}]}
JSON
exec weed server -dir=/data -s3 -s3.config=/tmp/s3.json -master.volumeSizeLimitMB=1024 -volume.max=100
