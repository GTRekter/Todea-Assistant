{{/*
Expand the name of the chart.
*/}}
{{- define "todea.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "todea.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Create component specific fullnames.
*/}}
{{- define "todea.componentName" -}}
{{- printf "%s-%s" (include "todea.fullname" .root) .component | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "todea.web.name" -}}
{{- include "todea.componentName" (dict "root" . "component" "web") -}}
{{- end -}}

{{- define "todea.mcp.name" -}}
{{- include "todea.componentName" (dict "root" . "component" "mcp") -}}
{{- end -}}

{{- define "todea.agentHub.name" -}}
{{- include "todea.componentName" (dict "root" . "component" "agent-hub") -}}
{{- end -}}

{{- define "todea.ollamaHub.name" -}}
{{- include "todea.componentName" (dict "root" . "component" "ollama-hub") -}}
{{- end -}}

{{- define "todea.ollamaRuntime.name" -}}
{{- include "todea.componentName" (dict "root" . "component" "ollama") -}}
{{- end -}}

{{- define "todea.conversationHub.name" -}}
{{- include "todea.componentName" (dict "root" . "component" "conversation-hub") -}}
{{- end -}}

{{/*
Default labels shared by objects.
*/}}
{{- define "todea.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "todea.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Selector labels (immutable across releases)
*/}}
{{- define "todea.selectorLabels" -}}
app.kubernetes.io/name: {{ include "todea.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Component specific selector labels
*/}}
{{- define "todea.web.selectorLabels" -}}
{{ include "todea.selectorLabels" . }}
app.kubernetes.io/component: web
{{- end -}}

{{- define "todea.mcp.selectorLabels" -}}
{{ include "todea.selectorLabels" . }}
app.kubernetes.io/component: mcp
{{- end -}}

{{- define "todea.agentHub.selectorLabels" -}}
{{ include "todea.selectorLabels" . }}
app.kubernetes.io/component: agent-hub
{{- end -}}

{{- define "todea.ollamaHub.selectorLabels" -}}
{{ include "todea.selectorLabels" . }}
app.kubernetes.io/component: ollama-hub
{{- end -}}

{{- define "todea.ollamaRuntime.selectorLabels" -}}
{{ include "todea.selectorLabels" . }}
app.kubernetes.io/component: ollama
{{- end -}}

{{- define "todea.conversationHub.selectorLabels" -}}
{{ include "todea.selectorLabels" . }}
app.kubernetes.io/component: conversation-hub
{{- end -}}

{{- define "todea.mcp.secretName" -}}
{{- printf "%s-secret" (include "todea.mcp.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "todea.agentHub.secretName" -}}
{{- printf "%s-secret" (include "todea.agentHub.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
