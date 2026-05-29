# Route 53 Domain For The Cloud Run Site

This app is deployed as a Django service on Google Cloud Run. Route 53 can keep
hosting DNS for the domain; it only needs records that point traffic to the
Cloud Run custom domain mapping.

The production domain is `sixdegreestojoerogan.com`.

## 1. Deploy Django With The Domain Allowed

Cloud Run will still serve the app at its default `.run.app` URL, but Django
must also trust the custom host:

```bash
make deploy CUSTOM_DOMAIN=sixdegreestojoerogan.com
```

For a `www` site, deploy with:

```bash
make deploy CUSTOM_DOMAIN=www.sixdegreestojoerogan.com
```

If both apex and `www` should work, set both values explicitly:

```bash
make deploy \
  DJANGO_ALLOWED_HOSTS=.run.app,sixdegreestojoerogan.com,www.sixdegreestojoerogan.com \
  DJANGO_CSRF_TRUSTED_ORIGINS=https://sixdegreestojoerogan.com,https://www.sixdegreestojoerogan.com
```

## 2. Create The Cloud Run Domain Mapping

In Google Cloud Console:

1. Go to Cloud Run.
2. Open the `podcast-network-web` service.
3. Choose `Manage custom domains`.
4. Add the domain, such as `sixdegreestojoerogan.com` or
   `www.sixdegreestojoerogan.com`.
5. Copy the DNS records Google shows for the mapping.

Google may ask you to verify domain ownership first. Use the TXT record it
provides and add that TXT record in Route 53.

## 3. Add Records In Route 53

In the Route 53 hosted zone for the domain, add the records from Cloud Run.

Typical shapes are:

- For `www.sixdegreestojoerogan.com`: create a `CNAME` record named `www`
  pointing to the Google target shown by Cloud Run.
- For `sixdegreestojoerogan.com`: create the `A` and `AAAA` records shown by
  Cloud Run.

Use the exact values from the Cloud Run domain mapping screen, because Google
uses those records to issue and renew the managed TLS certificate.

## 4. Wait For DNS And Certificate Issuance

DNS can take a few minutes, sometimes longer depending on TTLs. The Cloud Run
domain mapping page will show certificate status. Once it is active, verify:

```bash
curl -I https://sixdegreestojoerogan.com
```

The response should be a Django/Cloud Run response, not a DNS or certificate
error.
