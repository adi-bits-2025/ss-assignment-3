## Install Minikube (Windows)
winget install Kubernetes.minikube

## Install kubectl 
curl.exe -LO "https://dl.k8s.io/release/v1.36.0/bin/windows/amd64/kubectl.exe"

## 1. Ensure Minikube Is Running (Resolve the Earlier Hang)

```powershell
minikube delete --all --purge
docker rm -f minikube 2>$null   # if exists
docker pull gcr.io/k8s-minikube/kicbase:v0.0.50 # Pre-load base image
minikube start --driver=docker --base-image="gcr.io/k8s-minikube/kicbase:v0.0.50" # Start minikube with pre-pulled image
```

Verify with:

```powershell
kubectl cluster-info
kubectl get nodes
```

You should see a single `Ready` node.

---

## 2. Build Images Inside Minikube's Docker Daemon

Minikube runs its own Docker engine. To avoid a registry, build your service images directly there.  
From your project root:

```powershell
# Point your local Docker client to Minikube's daemon
minikube docker-env | Invoke-Expression   # on PowerShell
# If that doesn't work, use:
# & minikube -p minikube docker-env --shell powershell | Invoke-Expression

# Now build each service image (use the same Dockerfiles from the infra/ directory)
docker build -t patient-service:latest ./services/patient-service
docker build -t doctor-schedule-service:latest ./services/doctor-schedule-service
docker build -t appointment-service:latest ./services/appointment-service
docker build -t prescription-service:latest ./services/prescription-service
docker build -t billing-service:latest ./services/billing-service
docker build -t demo-ui:latest ./services/demo-ui   # if there is a demo-ui Dockerfile
# Prometheus and Grafana we'll use official images, no custom build needed.
```

Set `imagePullPolicy: Never` in all your Kubernetes deployments so Kubernetes uses the locally built images.

---

## 3. Create a Namespace (Optional but Recommended)

Organise everything under a namespace like `hms`:

```powershell
kubectl create namespace hms
kubectl config set-context --current --namespace=hms   # set default namespace
```

---

## 4. Persistent Storage for SQLite Databases

Each service uses SQLite and must persist its database file. Kubernetes can provide this via PersistentVolumeClaims (PVCs). Because Minikube is a single-node cluster, a simple `hostPath` or default storage class will work.

Create a file `hms-storage.yaml`:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: patient-db-pvc
  namespace: hms
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 256Mi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: doctor-db-pvc
  namespace: hms
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 256Mi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: appointment-db-pvc
  namespace: hms
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 256Mi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: prescription-db-pvc
  namespace: hms
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 256Mi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: billing-db-pvc
  namespace: hms
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 256Mi
```

Apply:
```powershell
kubectl apply -f hms-storage.yaml
```

---

## 5. Configuration and Secrets

Services need to know the URLs of other services. Use ConfigMaps to inject these.

Create `hms-config.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: hms-config
  namespace: hms
data:
  # These hostnames match the Kubernetes Service names (we'll create them later)
  PATIENT_SERVICE_URL: "http://patient-service:5001"
  DOCTOR_SCHEDULE_SERVICE_URL: "http://doctor-schedule-service:5002"
  APPOINTMENT_SERVICE_URL: "http://appointment-service:5003"
  PRESCRIPTION_SERVICE_URL: "http://prescription-service:5004"
  BILLING_SERVICE_URL: "http://billing-service:5005"
  # If your services use environment variables with different names, adjust accordingly.
---
apiVersion: v1
kind: Secret
metadata:
  name: hms-secret
  namespace: hms
type: Opaque
data:
  # Example: if any service needs a DB password (even for SQLite, it's file-based so not needed)
  # Add base64-encoded secrets here if required.
  # db-password: c2VjcmV0   # base64 'secret'
```

Apply it:
```powershell
kubectl apply -f hms-config.yaml
```

**Important**: Check the actual environment variable names your services use. Open your `docker-compose.yml` or the application code and replace the keys in the ConfigMap with those exact names. Common patterns: `PATIENT_SERVICE_HOST`, `PATIENT_SERVICE_PORT`, or a single `PATIENT_SERVICE_URL`. The ConfigMap above uses `_URL` for simplicity.

---

## 6. Deploy Each Microservice

We'll create a separate YAML file for each service (easier to manage). I'll show the complete example for the **Patient Service**; you then repeat the pattern for the other four services.

### 6.1 Patient Service (`patient-service.yaml`)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: patient-service
  namespace: hms
spec:
  replicas: 1              # DO NOT increase for SQLite - data consistency
  selector:
    matchLabels:
      app: patient-service
  template:
    metadata:
      labels:
        app: patient-service
    spec:
      containers:
        - name: patient-service
          image: patient-service:latest
          imagePullPolicy: Never    # because we built inside Minikube
          ports:
            - containerPort: 5001
          envFrom:
            - configMapRef:
                name: hms-config
            - secretRef:
                name: hms-secret
          # Liveness and readiness probes using the /health endpoint
          livenessProbe:
            httpGet:
              path: /health
              port: 5001
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /health
              port: 5001
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "256Mi"
              cpu: "200m"
          volumeMounts:
            - name: patient-db-storage
              mountPath: /app/data          # <-- ADJUST to where your app stores the SQLite file
      volumes:
        - name: patient-db-storage
          persistentVolumeClaim:
            claimName: patient-db-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: patient-service
  namespace: hms
spec:
  selector:
    app: patient-service
  ports:
    - port: 5001
      targetPort: 5001
  type: ClusterIP      # internal only
```

**Critical**: The `mountPath` must be the directory inside the container where the SQLite file is created. Check your Dockerfile or application code. Often it's `/app/data`, `/data`, or the working directory. If unsure, inspect the running container (e.g., `docker exec patient-service pwd` and see where `hms.db` sits). Adjust accordingly for every service.

### 6.2 Repeat for Other Services

Create similar files for:
- `doctor-schedule-service.yaml` (port 5002, PVC `doctor-db-pvc`)
- `appointment-service.yaml` (port 5003, PVC `appointment-db-pvc`)
- `prescription-service.yaml` (port 5004, PVC `prescription-db-pvc`)
- `billing-service.yaml` (port 5005, PVC `billing-db-pvc`)

Only change the service name, labels, port numbers, PVC name, and volume mount path. All of them use `envFrom` with the same `hms-config` ConfigMap.

---

## 7. Deploy Prometheus and Grafana (Monitoring)

Your existing Prometheus needs a configuration file that defines scrape targets. Create a ConfigMap with that configuration.

### 7.1 Prometheus ConfigMap (`prometheus-config.yaml`)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-config
  namespace: hms
data:
  prometheus.yml: |
    global:
      scrape_interval: 15s
    scrape_configs:
      - job_name: 'patient-service'
        static_configs:
          - targets: ['patient-service:5001']
      - job_name: 'doctor-schedule-service'
        static_configs:
          - targets: ['doctor-schedule-service:5002']
      - job_name: 'appointment-service'
        static_configs:
          - targets: ['appointment-service:5003']
      - job_name: 'prescription-service'
        static_configs:
          - targets: ['prescription-service:5004']
      - job_name: 'billing-service'
        static_configs:
          - targets: ['billing-service:5005']
```

### 7.2 Prometheus Deployment and Service (`prometheus-deployment.yaml`)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prometheus
  namespace: hms
spec:
  replicas: 1
  selector:
    matchLabels:
      app: prometheus
  template:
    metadata:
      labels:
        app: prometheus
    spec:
      containers:
        - name: prometheus
          image: prom/prometheus:latest
          ports:
            - containerPort: 9090
          volumeMounts:
            - name: config-volume
              mountPath: /etc/prometheus/prometheus.yml
              subPath: prometheus.yml
      volumes:
        - name: config-volume
          configMap:
            name: prometheus-config
---
apiVersion: v1
kind: Service
metadata:
  name: prometheus
  namespace: hms
spec:
  selector:
    app: prometheus
  ports:
    - port: 9090
  type: ClusterIP
```

### 7.3 Grafana (`grafana-deployment.yaml`)

Use the official image and expose on port 3000.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
  namespace: hms
spec:
  replicas: 1
  selector:
    matchLabels:
      app: grafana
  template:
    metadata:
      labels:
        app: grafana
    spec:
      containers:
        - name: grafana
          image: grafana/grafana:latest
          ports:
            - containerPort: 3000
---
apiVersion: v1
kind: Service
metadata:
  name: grafana
  namespace: hms
spec:
  selector:
    app: grafana
  ports:
    - port: 3000
  type: ClusterIP
```

---

## 8. Deploy Demo UI

The Demo UI is a React app with a backend (likely Flask or Nginx). This service needs to be accessible from outside the cluster because you interact with it in a browser. We'll expose it via a NodePort. Check the demo-ui Dockerfile for its exposed port; it’s 8501.

```yaml
# demo-ui.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo-ui
  namespace: hms
spec:
  replicas: 1
  selector:
    matchLabels:
      app: demo-ui
  template:
    metadata:
      labels:
        app: demo-ui
    spec:
      containers:
        - name: demo-ui
          image: demo-ui:latest
          imagePullPolicy: Never
          ports:
            - containerPort: 8501
          envFrom:
            - configMapRef:
                name: hms-config
          # The demo-ui might need its own specific environment variables.
          # If it calls backend APIs directly from the browser, we need to configure
          # API_BASE_URL to point to the external NodePort/IP. For simplicity,
          # we assume it uses the cluster-internal service names (server‑side proxy).
---
apiVersion: v1
kind: Service
metadata:
  name: demo-ui
  namespace: hms
spec:
  selector:
    app: demo-ui
  ports:
    - port: 8501
      targetPort: 8501
  type: NodePort      # Expose on a random port (30000-32767) on the Minikube VM
```

---

## 9. Apply All Manifests

Place all YAML files in a folder, e.g. `k8s/`, and apply:

```powershell
kubectl apply -f k8s/
```

Wait for all pods to be ready:

```powershell
kubectl get pods -n hms -w
```

Check services:

```powershell
kubectl get svc -n hms
```

---

## 10. Access the Demo UI

Find the NodePort assigned to the `demo-ui` service:

```powershell
kubectl get svc demo-ui -n hms
```

Example output:
```
NAME       TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)          AGE
demo-ui    NodePort   10.104.20.143   <none>        8501:32456/TCP   1m
```

Now open your browser at `http://<minikube-ip>:32456`. Get the Minikube IP with:

```powershell
minikube ip
```

Or simply use the Minikube service command:

```powershell
minikube service demo-ui -n hms --url
```

This will automatically open the browser.

---

## 11. Seed the Database

Now that all services are up, you can run your central seeding script. It needs to access the services via their Kubernetes service names. One easy way is to run the script from your local machine using port‑forwarding:

```powershell
Start-Job { kubectl port-forward -n hms svc/patient-service 5001:5001 }
Start-Job { kubectl port-forward -n hms svc/doctor-schedule-service 5002:5002 }
Start-Job { kubectl port-forward -n hms svc/appointment-service 5003:5003 }
Start-Job { kubectl port-forward -n hms svc/prescription-service 5004:5004 }
Start-Job { kubectl port-forward -n hms svc/billing-service 5005:5005 }
```

Wait a moment, then run the seeder from your project root (the script likely uses `localhost` or `127.0.0.1` by default; check `seed_all.py` and adjust if needed):

```powershell
cd services
python seed_all.py
```
After seeding, the Demo UI should reflect the data.

When you’re done testing, either close the PowerShell windows that run the kubectl port-forward commands, or stop the background jobs:
```powershell
Get-Job | Stop-Job
Get-Job | Remove-Job
```

**Alternative**: Run a Kubernetes Job that executes the seed script. That avoids port-forwarding but requires packaging the script into a Docker image. For a quick demo, port-forwarding is sufficient.

---

## 12. Explore Minikube and Kubernetes Features

Now that everything runs on Minikube, you can demonstrate orchestration capabilities:

- **Dashboard**: `minikube dashboard` (opens web UI)
- **Scaling** (though not recommended for SQLite): `kubectl scale deployment patient-service --replicas=2` (then watch it fail or show inconsistency – useful to explain why database-per-service matters)
- **Self-healing**: `kubectl delete pod -l app=patient-service` – Kubernetes will restart it automatically
- **Logs**: `kubectl logs -f deployment/patient-service`
- **Resource usage**: `kubectl top pods` (requires metrics-server enabled: `minikube addons enable metrics-server`)
- **Rolling update**: Rebuild a service image, then update the deployment image

---

## Summary of the Resulting Architecture

- Each microservice runs in its own Pod, with its own SQLite database stored on a PersistentVolume.
- Services discover each other via Kubernetes DNS (`patient-service:5001`).
- Configuration is externalised in ConfigMaps, keeping the containers stateless (except the DB file).
- All inter-service calls remain synchronous HTTP/REST, just like in Docker Compose.
- Monitoring with Prometheus/Grafana works because Prometheus scrapes the `/metrics` endpoints using internal service names.
- The demo UI is exposed externally while backend services remain internal, exactly as required.

This deployment meets all the assignment requirements: container orchestration with Minikube, proper Kubernetes manifests, and a live demonstration of microservices on a local cluster.