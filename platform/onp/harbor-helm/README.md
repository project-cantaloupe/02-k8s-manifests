# Harbor HTTPS endpoint

Harbor is exposed privately through Tailscale Serve:

- Public endpoint: `https://cntlp-onp-wk-01.tail270b85.ts.net`
- Backend NodePort: `http://127.0.0.1:32432`
- Argo CD remains mounted at `/argocd` on the same Tailscale hostname.

The node-level Serve configuration is persistent in `tailscaled` state but is
not a Kubernetes resource. Restore it after rebuilding `cntlp-onp-wk-01`:

```bash
tailscale serve --bg --https=443 --set-path=/ http://127.0.0.1:32432
tailscale serve --http=80 off
tailscale serve status
```

Keep the Helm `externalURL` set to the public HTTPS endpoint. Harbor uses it to
advertise `/service/token` to Docker clients; pointing it at the HTTP NodePort
causes Docker to receive an HTTP token realm even when `/v2/` is accessed over
HTTPS.

Basic verification:

```bash
curl -fsS https://cntlp-onp-wk-01.tail270b85.ts.net/api/v2.0/health
curl -sSI https://cntlp-onp-wk-01.tail270b85.ts.net/v2/
```
