@echo off
docker build -f longplay/host/Dockerfile -t vcmi-host .
docker run --rm --name vcmi_host -p 3000:3000 -p 3001:3001 vcmi-host