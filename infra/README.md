# Azure deployment notes

`main.bicep` provisions the API and independent Worker Container Apps plus the
minimum Storage, Queue, Blob and Log Analytics resources. The Worker claims
Azure Queue messages, executes the deterministic workflow, persists the result,
and acknowledges or retries each message. It also assigns both app identities the
Storage Blob, Queue and Table Data Contributor roles. It intentionally does
not create a public registry, store an API key, or grant ACR administrator
credentials. Configure a private registry and managed identity access in the target subscription, then deploy
with an operator-controlled command:

```bash
az deployment group create \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --template-file infra/main.bicep \
  --parameters @infra/parameters.example.json \
  --parameters containerImage="$CONTAINER_IMAGE"
```

Before production use, add Entra ID authentication, Key Vault references, and
the Cognitive Services/OpenAI User role on the external model resource if an
Azure OpenAI provider is enabled. Keep
`evaluator_private`, local databases, tokens, and real customer data outside
the build context. The template enables external HTTPS ingress for the API;
restrict it with Container Apps authentication or a private network before
using it with non-synthetic data.
