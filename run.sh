#!/bin/bash
set -e

docker build -t realmdeathsnitch .
docker rm -f realmdeathsnitch_container 2>/dev/null || true
docker run -d \
  --name realmdeathsnitch_container \
  --restart unless-stopped \
  realmdeathsnitch
