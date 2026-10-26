param location string = resourceGroup().location
param namePrefix string = 'decisionflow'
param containerImage string
param containerPort int = 8000
param minReplicas int = 1
param maxReplicas int = 3

var unique = uniqueString(resourceGroup().id)
var storageName = take(replace(toLower('${namePrefix}${unique}'), '-', ''), 24)
var envName = '${namePrefix}-env'
var appName = '${namePrefix}-api'
var blobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var queueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
var tableDataContributorRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${namePrefix}-logs'
  location: location
  properties: {
    retentionInDays: 30
    sku: { name: 'PerGB2018' }
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource artifacts 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'decisionflow-artifacts'
  properties: { publicAccess: 'None' }
}

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource jobsQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queueService
  name: 'decisionflow-jobs'
}

resource environment 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

resource app 'Microsoft.App/containerApps@2023-05-01' = {
  name: appName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: {
        external: true
        targetPort: containerPort
        transport: 'http'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'decisionflow-api'
          image: containerImage
          resources: { cpu: 1, memory: '1Gi' }
          env: [
            { name: 'DECISIONFLOW_DATA_ROOT', value: '/app/data/public_v02' }
            { name: 'DECISIONFLOW_RUN_STORE', value: 'azure_table' }
            { name: 'DECISIONFLOW_AUDIT_STORE', value: 'azure_table' }
            { name: 'DECISIONFLOW_QUEUE_BACKEND', value: 'azure' }
            { name: 'DECISIONFLOW_PROVIDER', value: 'mock' }
            { name: 'AZURE_STORAGE_ACCOUNT_URL', value: 'https://${storage.name}.table.core.windows.net' }
            { name: 'AZURE_STORAGE_QUEUE_URL', value: 'https://${storage.name}.queue.core.windows.net' }
            { name: 'AZURE_QUEUE_NAME', value: 'decisionflow-jobs' }
            { name: 'AZURE_BLOB_CONTAINER', value: 'decisionflow-artifacts' }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          { name: 'http', http: { metadata: { concurrentRequests: '20' } } }
        ]
      }
    }
  }
}

resource worker 'Microsoft.App/containerApps@2023-05-01' = {
  name: '${appName}-worker'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: environment.id
    template: {
      containers: [
        {
          name: 'decisionflow-worker'
          image: containerImage
          command: ['decisionflow-worker']
          resources: { cpu: 1, memory: '1Gi' }
          env: [
            { name: 'DECISIONFLOW_DATA_ROOT', value: '/app/data/public_v02' }
            { name: 'DECISIONFLOW_RUN_STORE', value: 'azure_table' }
            { name: 'DECISIONFLOW_AUDIT_STORE', value: 'azure_table' }
            { name: 'DECISIONFLOW_QUEUE_BACKEND', value: 'azure' }
            { name: 'DECISIONFLOW_PROVIDER', value: 'mock' }
            { name: 'AZURE_STORAGE_ACCOUNT_URL', value: 'https://${storage.name}.table.core.windows.net' }
            { name: 'AZURE_STORAGE_QUEUE_URL', value: 'https://${storage.name}.queue.core.windows.net' }
            { name: 'AZURE_QUEUE_NAME', value: 'decisionflow-jobs' }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

resource blobDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, app.id, blobDataContributorRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource queueDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, app.id, queueDataContributorRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueDataContributorRoleId)
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource tableDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, app.id, tableDataContributorRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', tableDataContributorRoleId)
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource workerBlobDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, worker.id, blobDataContributorRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
    principalId: worker.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource workerQueueDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, worker.id, queueDataContributorRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueDataContributorRoleId)
    principalId: worker.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource workerTableDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, worker.id, tableDataContributorRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', tableDataContributorRoleId)
    principalId: worker.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output containerAppName string = app.name
output containerAppFqdn string = app.properties.configuration.ingress.fqdn
output workerAppName string = worker.name
output storageAccountName string = storage.name
