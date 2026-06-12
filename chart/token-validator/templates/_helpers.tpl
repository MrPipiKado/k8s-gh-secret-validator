{{/* Chart name, optionally overridden. */}}
{{- define "token-validator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Fully qualified app name. */}}
{{- define "token-validator.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "token-validator.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "token-validator.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "token-validator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
{{- end -}}

{{- define "token-validator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "token-validator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* ServiceAccount name to use. */}}
{{- define "token-validator.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "token-validator.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* Name of the Secret holding the Teams webhook (chart-managed or external). */}}
{{- define "token-validator.teamsSecretName" -}}
{{- if .Values.teamsWebhook.existingSecret -}}
{{- .Values.teamsWebhook.existingSecret -}}
{{- else -}}
{{- printf "%s-teams" (include "token-validator.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/* Whether Teams alerting is on (driven by the app config). */}}
{{- define "token-validator.teamsEnabled" -}}
{{- dig "notifiers" "teams" "enabled" false .Values.config -}}
{{- end -}}
