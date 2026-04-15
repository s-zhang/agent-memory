FROM ghcr.io/getzep/zep:latest

# Override the config file with one generated from env vars at startup.
# The base image has broken Viper env-var binding for store.type so we must
# write the value directly into config.yaml via this entrypoint.
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
