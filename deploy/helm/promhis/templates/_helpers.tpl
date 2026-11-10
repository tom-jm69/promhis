{{/*
Expand the name of the chart.
*/}}
{{- define "promhis.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "promhis.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "promhis.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "promhis.labels" -}}
helm.sh/chart: {{ include "promhis.chart" . }}
{{ include "promhis.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "promhis.selectorLabels" -}}
app.kubernetes.io/name: {{ include "promhis.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "promhis.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "promhis.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Name of the bundled Postgres Deployment/Service/PVC/Secret, when enabled.
*/}}
{{- define "promhis.postgresFullname" -}}
{{- printf "%s-postgres" (include "promhis.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Resolve the bundled Postgres password: explicit value, else whatever an
earlier install already generated (read back from the live cluster so
`helm upgrade` never silently rotates it and breaks the existing DB
connection), else a fresh random one. `lookup` returns an empty result
under `helm template`/`--dry-run` (no live cluster to query) and so always
falls through to a freshly generated value there — fine for rendering/
linting, never used for a real install's actual Secret in that case.

This is called from two different templates (the bundled Postgres's own
Secret, and the app's Secret when building its PROMHIS_DATABASE_URL) that
must agree on the same value — a plain `randAlphaNum` here would mint a
*different* random password each time it's called, silently breaking the
connection between them. The first call resolves it and writes the result
back into .Values.postgresql.auth.password (maps are shared by reference
across every template in one render), so every later call just reads that
already-resolved value back out instead of generating its own.
*/}}
{{- define "promhis.postgresPassword" -}}
{{- if not .Values.postgresql.auth.password }}
{{- $existing := lookup "v1" "Secret" .Release.Namespace (include "promhis.postgresFullname" .) }}
{{- if and $existing (hasKey $existing.data "postgres-password") }}
{{- $_ := set .Values.postgresql.auth "password" (index $existing.data "postgres-password" | b64dec) }}
{{- else }}
{{- $_ := set .Values.postgresql.auth "password" (randAlphaNum 24) }}
{{- end }}
{{- end }}
{{- .Values.postgresql.auth.password }}
{{- end }}
