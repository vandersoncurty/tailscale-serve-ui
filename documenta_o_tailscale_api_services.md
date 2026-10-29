# Services

Manage Tailscale Services for a tailnet. Learn more about [Tailscale Services](https://tailscale.com/kb/1236/tailscale-services).

## Operations

* `GET /tailnet/{tailnet}/services`
* `GET /tailnet/{tailnet}/services/{serviceName}`
* `PUT /tailnet/{tailnet}/services/{serviceName}`
* `DELETE /tailnet/{tailnet}/services/{serviceName}`
* `GET /tailnet/{tailnet}/services/{serviceName}/devices`
* `GET /tailnet/{tailnet}/services/{serviceName}/device/{deviceId}/approved`
* `POST /tailnet/{tailnet}/services/{serviceName}/device/{deviceId}/approved`

---

## List all Services

List all Services configured for the tailnet. This includes all Services in the "advertised" tab of the Services page in the Tailscale admin console.

* **OAuth Scope:** `services:read`
* **Authentication:** Required

### Path Parameters

* **`tailnet`** (*string*, **required**): The tailnet ID.
  * Tailnets created before Oct 2025 can still use the legacy ID, but the Tailnet ID is the preferred identifier.
  * When specifying a tailnet in the API, you can:
    * Provide a dash (`-`) to reference the default tailnet of the access token being used to make the API call. This is the best option for most users. Your API calls would start:
      ```bash
      curl "https://api.tailscale.com/api/v2/tailnet/-/... "
      ```
    * Provide the **tailnet ID** found on the **General Settings** page of the Tailscale admin console. For example, if your tailnet ID name is `T1234CNTRL`, your API calls would start:
      ```bash
      curl "https://api.tailscale.com/api/v2/tailnet/T1234CNTRL/... "
      ```

### Request Example

```bash
curl https://api.tailscale.com/api/v2/tailnet/example.com/services \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

### Responses

* **`200`** Successful operation.

#### Response Body Example (200)

```json
{
  "vipServices": [
    {
      "name": "svc:example",
      "displayName": "Example Service",
      "addrs": [
        "100.93.49.180",
        "fd7a:115c:a1e0::3456:3cb4"
      ],
      "comment": "Example Service",
      "ports": [
        "tcp:80",
        "tcp:443"
      ],
      "tags": [
        "tag:example"
      ]
    }
  ]
}
```

* **`400`** Bad request.
* **`403`** Forbidden.
* **`404`** Not found.
* **`500`** Internal server error.

---

## Get a Service

Retrieve the details for the specified Service.

* **OAuth Scope:** `services:read`
* **Authentication:** Required

### Path Parameters

* **`tailnet`** (*string*, **required**): The tailnet ID. (See rules above).
* **`serviceName`** (*string*, **required**): The unique name of a Service. The name should be prefixed with "svc:". It should be unique across the tailnet, so names already used for a machine cannot be reused for a Service.

### Request Example

```bash
curl https://api.tailscale.com/api/v2/tailnet/example.com/services/svc:example \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

### Responses

* **`200`** Successful operation.

#### Response Body Example (200)

```json
{
  "name": "svc:example",
  "displayName": "Example Service",
  "addrs": [
    "100.93.49.180",
    "fd7a:115c:a1e0::3456:3cb4"
  ],
  "comment": "Example Service",
  "ports": [
    "tcp:80",
    "tcp:443"
  ],
  "tags": [
    "tag:example"
  ]
}
```

* **`400`** Bad request.
* **`403`** Forbidden.
* **`404`** Not found.
* **`500`** Internal server error.
* **`504`** Gateway timeout.

---

## Update a Service

Update or create the specified Service. If the Service does not exist, it will create a Service with the provided details. When creating a new Service, the name in the request body must match the serviceName path parameter. When updating an existing Service, the path parameter is the current name of the Service, and the name in the request body can be used to rename the Service.

* **OAuth Scope:** `services`
* **Authentication:** Required

### Path Parameters

* **`tailnet`** (*string*, **required**): The tailnet ID. (See rules above).
* **`serviceName`** (*string*, **required**): The unique name of a Service.

### Body (`VIPServiceInfoPut` - `application/json`)

The Service details to create or update.

* **`addrs`** (*array[string]*): The IP addresses assigned to the Service.
  * For new Services: either unset or a single IPv4 to assign the Service.
  * For existing Services: an IPv4 and an IPv6. The IPv4 can be updated, but not the IPv6.
* **`comment`** (*string*): An optional comment for the Service.
* **`displayName`** (*string*, max length: 64): An optional human-readable label for the Service, shown in the Tailscale admin console and to clients with access to the Service. Must be 64 characters or fewer.
* **`name`** (*string*): The unique name of the Service.
* **`ports`** (*array[string]*): A list of protocol:port pairs to be exposed by the Service. The only supported protocol is "tcp" at this time. "do-not-validate" can be used to skip validation.
* **`tags`** (*array[string]*): A list of optional tags associated with the Service.

### Request Example

```bash
curl https://api.tailscale.com/api/v2/tailnet/example.com/services/svc:example \
  --request PUT \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN' \
  --data '{
  "addrs": [
    "100.93.49.180",
    "fd7a:115c:a1e0::3456:3cb4"
  ],
  "name": "svc:example",
  "displayName": "Example Service",
  "comment": "Example Service",
  "ports": [
    "tcp:80",
    "tcp:443"
  ],
  "tags": [
    "tag:example"
  ]
}'
```

### Responses

* **`200`** Successful operation.

#### Response Body Example (200)

```json
{
  "name": "svc:example",
  "displayName": "Example Service",
  "addrs": [
    "100.93.49.180",
    "fd7a:115c:a1e0::3456:3cb4"
  ],
  "comment": "Example Service",
  "ports": [
    "tcp:80",
    "tcp:443"
  ],
  "tags": [
    "tag:example"
  ]
}
```

* **`400`** Bad request.
* **`403`** Forbidden.
* **`404`** Not found.
* **`500`** Internal server error.
* **`504`** Gateway timeout.

---

## Delete a Service

Delete the specified Service from the tailnet.

* **OAuth Scope:** `services`
* **Authentication:** Required

### Path Parameters

* **`tailnet`** (*string*, **required**): The tailnet ID. (See rules above).
* **`serviceName`** (*string*, **required**): The unique name of a Service.

### Request Example

```bash
curl https://api.tailscale.com/api/v2/tailnet/example.com/services/svc:example \
  --request DELETE \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

### Responses

* **`200`** Successful operation (No Body).
* **`400`** Bad request.
* **`403`** Forbidden.
* **`404`** Not found.
* **`500`** Internal server error.
* **`504`** Gateway timeout.

---

## List devices hosting a Service

List all devices that are hosting the specified Service.

* **OAuth Scope:** `services`, `devices:core`
* **Authentication:** Required

### Path Parameters

* **`tailnet`** (*string*, **required**): The tailnet ID. (See rules above).
* **`serviceName`** (*string*, **required**): The unique name of a Service.

### Request Example

```bash
curl https://api.tailscale.com/api/v2/tailnet/example.com/services/svc:example/devices \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

### Responses

* **`200`** Successful operation.

#### Response Body Example (200)

```json
{
  "hosts": [
    {
      "stableNodeID": "n292kg92CNTRL",
      "approvalLevel": "not-approved",
      "configured": "ready"
    }
  ]
}
```

* **`400`** Bad request.
* **`403`** Forbidden.
* **`404`** Not found.
* **`500`** Internal server error.
* **`504`** Gateway timeout.

---

## Get approval status of Service on a device

Retrieve the approval status of the specified Service on a specific device.

* **OAuth Scope:** `services`, `devices:core`
* **Authentication:** Required

### Path Parameters

* **`tailnet`** (*string*, **required**): The tailnet ID. (See rules above).
* **`serviceName`** (*string*, **required**): The unique name of a Service.
* **`deviceId`** (*string*, **required**): ID of the device. Using the device's `nodeId` is preferred, but its numeric `id` value can also be used.

### Request Example

```bash
curl 'https://api.tailscale.com/api/v2/tailnet/example.com/services/svc:example/device/deviceId/approved' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

### Responses

* **`200`** Successful operation.

#### Response Body Example (200)

```json
{
  "approved": true,
  "autoApproved": true
}
```

* **`400`** Bad request.
* **`403`** Forbidden.
* **`404`** Not found.
* **`500`** Internal server error.
* **`504`** Gateway timeout.

---

## Update approval status of Service on a device

Update the approval status of the specified Service on a specific device.

* **OAuth Scope:** `services`, `devices:core`
* **Authentication:** Required

### Path Parameters

* **`tailnet`** (*string*, **required**): The tailnet ID. (See rules above).
* **`serviceName`** (*string*, **required**): The unique name of a Service.
* **`deviceId`** (*string*, **required**): ID of the device. Using the device's `nodeId` is preferred, but its numeric `id` value can also be used.

### Body (`application/json`)

The approval status to set for the Service on the device.

* **`approved`** (*boolean*): Indicates whether to approve or revoke approval for the Service on the device.

### Request Example

```bash
curl 'https://api.tailscale.com/api/v2/tailnet/example.com/services/svc:example/device/deviceId/approved' \
  --request POST \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN' \
  --data '{
  "approved": true
}'
```

### Responses

* **`200`** Successful operation.

#### Response Body Example (200)

```json
{
  "approved": true,
  "autoApproved": true
}
```

* **`400`** Bad request.
* **`403`** Forbidden.
* **`404`** Not found.
* **`500`** Internal server error.