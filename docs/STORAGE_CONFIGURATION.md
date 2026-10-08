# BluePace ATS Storage Configuration

## Private object storage

The backend storage abstraction supports **Cloudflare R2**, **Backblaze B2**, and a local filesystem fallback.

Provider selection:

1. R2 when all R2 variables are configured.
2. B2 when R2 is not configured and all B2 variables are configured.
3. Local filesystem otherwise.

### Cloudflare R2

Set these on the backend service:

```
R2_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=<access-key>
R2_SECRET_ACCESS_KEY=<secret-key>
R2_BUCKET=<bucket-name>
R2_REGION=auto
```

Recommended private key layout:

```
resumes/
job-descriptions/
offers/
candidate-documents/
```

The browser must never receive the R2 secret key. Use presigned upload/download URLs for direct object access.

### Backblaze B2

The legacy B2-compatible variables remain supported:

```
B2_ENDPOINT=<s3-compatible-endpoint>
B2_ACCESS_KEY_ID=<key-id>
B2_SECRET_ACCESS_KEY=<application-key>
B2_BUCKET=<bucket-name>
B2_REGION=<region>
```

### Local fallback

When neither provider is configured, the backend uses:

```
RESUME_STORAGE_DIR=./private_uploads
```

This is a development/demo fallback. It is not durable object storage across service replacement.

## Public media

Cloudinary is isolated from private ATS files.

```
CLOUDINARY_CLOUD_NAME=<cloud-name>
CLOUDINARY_API_KEY=<api-key>
CLOUDINARY_API_SECRET=<api-secret>
CLOUDINARY_PUBLIC_FOLDER=careers-site
```

Use Cloudinary for public careers-site images/video/PDF assets. Do not use it as the default repository for private candidate resumes.

## Current rollout status

The application code is R2-ready. The connected Cloudflare account must first have R2 enabled and a bucket/API token created before R2 becomes the active provider.
