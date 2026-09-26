# Fix only the upstream shell-based health check in this shell-free image.
FROM docker.gitea.com/gitea-mcp-server@sha256:273827c5cf8fec3846c09bd35461b59bdd06941bdcfcfefd388cbc22f2343f6b
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s CMD ["/app/gitea-mcp", "-healthcheck"]
