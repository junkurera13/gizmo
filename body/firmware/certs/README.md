# Friend TLS roots

HTTPS health checks and WSS both use the ISRG Root X1 and X2 certificates in
this directory, embedded in `include/gizmo/trust_roots.h`. They are public CA
certificates from the Mozilla trust store distributed with certifi. No device
secret or leaf certificate is embedded. The Railway brain's public chain was
checked on 2026-09-07 and chains to ISRG Root X2.

SHA-256 of each certificate's DER representation:

- X1: `96bcec06264976f37460779acf28c5a7cfe8a3c0aae11a8ffcee05c0bddf08c6`
- X2: `69729b8e15a86efc177a57afb7171dfc64add28c2fca8cf1507e34453ccb1470`

Certificate verification includes the requested hostname and validity dates.
Firmware waits for network time before making TLS connections. A server using
another CA requires adding its verified root here and rebuilding the header;
never fall back to skip-verification. Plain HTTP remains available for local
LAN bring-up only. Use HTTPS with the Railway URL.

Regenerate the header after reviewing CA changes:

```sh
python3 body/firmware/tools/embed_trust_roots.py
```

CA source information: https://letsencrypt.org/certificates/
