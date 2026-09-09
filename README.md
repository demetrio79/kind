# Kind GitOps Lab

Laboratório local de Kubernetes com Kind, ArgoCD e GitHub Actions. Simula uma esteira completa de CI/CD com ambientes de DEV e PRD, promoção automatizada e GitOps.

---

## Visão Geral

```
GitHub (repositório) ──► GitHub Actions (CI) ──► ArgoCD (CD/GitOps) ──► Kind (cluster local)
```

- **Kind** provisiona um cluster Kubernetes local com 1 control-plane e 2 workers
- **ArgoCD** monitora o repositório e sincroniza automaticamente os manifestos no cluster
- **GitHub Actions** valida, testa em DEV e abre PR de promoção para PRD
- **Kustomize** gerencia as diferenças entre os ambientes (DEV e PRD)

---

## Estrutura do Repositório

```
kind/
├── cluster/
│   ├── kind-multinode.yaml          # Configuração do cluster Kind (1 control-plane + 2 workers)
│   └── ArgoCD/
│       ├── argo-ingress.yaml        # Ingress do ArgoCD (argo.local)
│       ├── argocd-cmd-params-cm.yaml# ConfigMap para modo insecure (HTTP)
│       ├── demo-app-dev.yaml        # ArgoCD Application - ambiente DEV
│       └── demo-app-prd.yaml        # ArgoCD Application - ambiente PRD
├── apps/
│   └── demo-app/
│       ├── base/                    # Manifests base (Deployment + Service)
│       │   ├── deployment.yaml
│       │   ├── service.yaml
│       │   └── kustomization.yaml
│       ├── dev/                     # Overlay DEV (2 réplicas, host dev.local)
│       │   ├── kustomization.yaml
│       │   ├── configmap.yaml
│       │   └── ingress.yaml
│       └── prd/                     # Overlay PRD (5 réplicas, host prd.local)
│           ├── kustomization.yaml
│           ├── configmap.yaml
│           └── ingress.yaml
├── scripts/
│   └── promote.py                   # Script de promoção DEV → PRD
└── .github/
    └── workflows/
        ├── auto-pr.yml              # Cria PR automaticamente em qualquer push de branch
        └── pipeline-dev-prd.yml    # Pipeline principal: valida, testa e promove para PRD
```

---

## Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/)
- [Kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- [ArgoCD CLI](https://argo-cd.readthedocs.io/en/stable/cli_installation/) (opcional)

---

## Setup do Cluster

### 1. Criar o cluster Kind

```bash
kind create cluster --config cluster/kind-multinode.yaml --name kind
```

Cluster criado com:
- 1 control-plane
- 2 workers

### 2. Instalar o NGINX Ingress Controller

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=90s
```

### 3. Instalar o ArgoCD

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl wait --for=condition=available deployment --all -n argocd --timeout=120s
```

### 4. Configurar o ArgoCD (modo HTTP + ingress)

```bash
kubectl apply -f cluster/ArgoCD/argocd-cmd-params-cm.yaml
kubectl apply -f cluster/ArgoCD/argo-ingress.yaml
kubectl rollout restart deployment argocd-server -n argocd
```

### 5. Configurar o `/etc/hosts`

```bash
echo "172.18.0.2 argo.local dev.local prd.local" | sudo tee -a /etc/hosts
```

### 6. Criar as Applications no ArgoCD

```bash
kubectl apply -f cluster/ArgoCD/demo-app-dev.yaml
kubectl apply -f cluster/ArgoCD/demo-app-prd.yaml
```

---

## Acessos

| Serviço      | URL                          | Usuário | Senha                          |
|-------------|-------------------------------|---------|-------------------------------|
| ArgoCD UI   | http://argo.local             | admin   | ver comando abaixo             |
| App DEV     | http://dev.local              | -       | -                              |
| App PRD     | http://prd.local              | -       | -                              |

**Recuperar senha do ArgoCD:**

```bash
kubectl get secret argocd-initial-admin-secret -n argocd \
  -o jsonpath="{.data.password}" | base64 -d && echo
```

---

## Ambientes da Aplicação

### DEV (`demo-app-dev`)

| Parâmetro   | Valor             |
|-------------|-------------------|
| Namespace   | `demo-app-dev`    |
| Réplicas    | 2                 |
| Host        | `dev.local`       |
| nip.io      | `dev.172.18.0.2.nip.io` |
| Imagem      | `nginx:alpine`    |

### PRD (`demo-app-prd`)

| Parâmetro   | Valor             |
|-------------|-------------------|
| Namespace   | `demo-app-prd`    |
| Réplicas    | 5                 |
| Host        | `prd.local`       |
| nip.io      | `prd.172.18.0.2.nip.io` |
| Imagem      | `nginx:alpine`    |

Os ambientes são gerenciados com **Kustomize**. O base define o Deployment e Service, e cada overlay (dev/prd) customiza réplicas, ConfigMap com HTML e Ingress.

---

## Pipelines GitHub Actions

### `auto-pr.yml` — Auto Pull Request

Disparado em qualquer push para branches que não sejam `main` ou `release/**`.

- Verifica se já existe um PR aberto para a branch
- Se não existir, cria automaticamente um PR apontando para `main`

### `pipeline-dev-prd.yml` — Pipeline DEV → PRD

Disparado em push para `main` quando há alterações em `apps/demo-app/dev/**` ou `apps/demo-app/base/**`.

**Job 1 — Validar e Testar DEV:**
1. Valida a sintaxe dos manifestos com `kubectl kustomize`
2. Sobe um cluster Kind temporário **dentro do próprio runner do GitHub Actions** (`ci-test-cluster`) — não tem relação com o cluster local
3. Aplica os manifestos de DEV nesse cluster temporário
4. Aguarda o rollout dos pods
5. Executa **Smoke Test HTTP** via port-forward (espera HTTP 200)
6. O cluster temporário é descartado automaticamente ao final do job

**Job 2 — Promover para PRD** (depende do Job 1):
1. Cria uma branch `release/promote-to-prd-<run_number>`
2. Executa `scripts/promote.py` para sincronizar o configmap de DEV para PRD
3. Se houver diferença, faz commit e push
4. Abre PR automático: *"PROMOÇÃO: DEV para PRD (Validado)"*

---

## Script de Promoção (`scripts/promote.py`)

Copia o `configmap.yaml` de DEV para PRD realizando as substituições necessárias:

- Namespace: `demo-app-dev` → `demo-app-prd`
- Labels/textos: `DEV` → `PRODUÇÃO`
- Hosts: `dev.local` → `prd.local` / `dev.172.18.0.2.nip.io` → `prd.172.18.0.2.nip.io`
- Cores do tema: amarelo (DEV) → verde (PRD)

```bash
python3 scripts/promote.py
```

---

## GitOps — Fluxo Completo

```
1. Developer cria branch feature/xxx
        │
        ▼
2. Push → auto-pr.yml abre PR para main
        │
        ▼
3. Merge em main (apps/demo-app/dev/)
        │
        ▼
4. pipeline-dev-prd.yml dispara
   ├── Valida Kustomize
   ├── Sobe Kind no runner
   ├── Deploy em DEV
   ├── Smoke Test HTTP 200
   └── promote.py → abre PR release/promote-to-prd-N
        │
        ▼
5. Merge do PR de promoção em main
        │
        ▼
6. ArgoCD detecta mudança no Git
   ├── Sincroniza demo-app-dev  (namespace demo-app-dev)
   └── Sincroniza demo-app-prd  (namespace demo-app-prd)
```

---

## Git — Fluxo de Trabalho

### Repositório

```
https://github.com/demetrio79/kind.git
```

### Branches

| Branch | Descrição |
|--------|-----------|
| `main` | Branch principal **protegida**. Push direto bloqueado — aceita apenas merges via Pull Request. |
| `feature/<nome>` | Novas funcionalidades na aplicação ou infraestrutura |
| `fix/<nome>` | Correções de bugs ou problemas de pipeline |
| `release/promote-to-prd-<N>` | Criada automaticamente pela pipeline ao promover DEV → PRD |
| `argocd/<nome>` | Alterações de configuração do ArgoCD |

### Convenção de Commits (Conventional Commits)

```
<tipo>(<escopo opcional>): <descrição curta>
```

| Tipo | Quando usar |
|------|-------------|
| `feat` | Nova funcionalidade |
| `fix` | Correção de bug |
| `chore` | Tarefas de manutenção, sem impacto funcional |
| `ci` | Alterações em pipelines / GitHub Actions |
| `docs` | Documentação |

Exemplos reais do projeto:
```
feat(dev): release version 2.0 with new features
fix: use robust port-forward in smoke test
ci: add dev to prd promotion pipeline and argo-ingress
chore: scale demo-app to 4 replicas
chore(release): promote dev changes to prd [skip ci]
```

> Use `[skip ci]` no final da mensagem quando não quiser disparar a pipeline (ex: commits automáticos de promoção).

---

### Fluxo Diário — Passo a Passo

#### 1. Atualizar o repositório local

Sempre parta do `main` atualizado:

```bash
git checkout main
git pull origin main
```

> **Atenção:** `main` tem proteção de branch ativada no GitHub. Push direto é bloqueado — qualquer alteração precisa passar por Pull Request. Tentativas de `git push origin main` serão rejeitadas.

#### 2. Criar uma branch para a tarefa

```bash
# Nova funcionalidade
git checkout -b feature/nome-da-feature

# Correção
git checkout -b fix/descricao-do-fix

# Configuração do ArgoCD ou cluster
git checkout -b argocd/descricao-da-mudanca
```

#### 3. Fazer as alterações e commitar

```bash
# Ver o que foi alterado
git status

# Adicionar arquivos específicos (evite git add . para não commitar arquivos indesejados)
git add apps/demo-app/dev/configmap.yaml

# Ou adicionar tudo de uma pasta específica
git add apps/demo-app/dev/

# Commitar com mensagem descritiva
git commit -m "feat(dev): atualiza layout da página inicial"
```

#### 4. Subir a branch para o GitHub

```bash
# Primeiro push da branch (cria o tracking remoto)
git push -u origin feature/nome-da-feature

# Pushes seguintes
git push
```

> O workflow `auto-pr.yml` detecta o push e cria o PR automaticamente apontando para `main`.

#### 5. Abrir Pull Request (se não foi criado automaticamente)

```bash
gh pr create \
  --base main \
  --head feature/nome-da-feature \
  --title "feat: descrição da mudança" \
  --body "Descrição detalhada do que foi alterado e por quê."
```

#### 6. Merge do PR em `main`

Faça o merge pelo GitHub. Após o merge:

- Se as alterações forem em `apps/demo-app/dev/**` ou `apps/demo-app/base/**`, a pipeline `pipeline-dev-prd.yml` dispara automaticamente
- O ArgoCD detecta a mudança no Git e sincroniza o cluster

---

### Cenário 1 — Atualizar a aplicação em DEV

```bash
git checkout main && git pull
git checkout -b feature/minha-feature

# Editar o configmap de DEV
vim apps/demo-app/dev/configmap.yaml

git add apps/demo-app/dev/configmap.yaml
git commit -m "feat(dev): descreve a mudança"
git push -u origin feature/minha-feature

# PR criado automaticamente pelo auto-pr.yml
# Após merge em main:
#   → pipeline valida, testa e abre PR de promoção para PRD
#   → ArgoCD sincroniza DEV automaticamente
```

### Cenário 2 — Promover manualmente para PRD

Se precisar promover sem passar pela pipeline:

```bash
git checkout main && git pull
git checkout -b release/promote-manual

python3 scripts/promote.py

git add apps/demo-app/prd/configmap.yaml
git commit -m "chore(release): promote dev changes to prd [skip ci]"
git push -u origin release/promote-manual

gh pr create --base main --head release/promote-manual \
  --title "PROMOÇÃO: DEV para PRD (manual)" \
  --body "Promoção manual do configmap de DEV para PRD."
```

### Cenário 3 — Alterar configuração do cluster (ArgoCD, ingress, etc.)

```bash
git checkout main && git pull
git checkout -b argocd/descricao

# Editar manifests em cluster/ArgoCD/
vim cluster/ArgoCD/argo-ingress.yaml

git add cluster/ArgoCD/
git commit -m "argocd: descreve a mudança"
git push -u origin argocd/descricao

# Após merge via PR (main é protegido, push direto é bloqueado),
# aplicar manualmente no cluster (ArgoCD não gerencia a si mesmo):
kubectl apply -f cluster/ArgoCD/
```

### Cenário 4 — Corrigir um problema na pipeline

```bash
git checkout main && git pull
git checkout -b fix/descricao-do-problema

# Editar o workflow
vim .github/workflows/pipeline-dev-prd.yml

git add .github/workflows/pipeline-dev-prd.yml
git commit -m "fix: descreve a correção na pipeline"
git push -u origin fix/descricao-do-problema
```

---

### Comandos Git do Dia a Dia

```bash
# Ver status atual
git status

# Ver branches locais e remotas
git branch -a

# Ver histórico resumido
git log --oneline -10

# Ver histórico com grafo de branches
git log --oneline --graph --all -15

# Atualizar branch local com o remoto sem merge
git fetch origin

# Sincronizar branch com main (rebase)
git fetch origin
git rebase origin/main

# Desfazer último commit (mantém as alterações no disco)
git reset HEAD~1

# Descartar alterações em um arquivo
git restore apps/demo-app/dev/configmap.yaml

# Ver diferença antes de commitar
git diff apps/demo-app/dev/configmap.yaml

# Listar PRs abertos
gh pr list

# Ver status de um PR específico
gh pr view <número>

# Fazer checkout de um PR para testar localmente
gh pr checkout <número>
```

---

```bash
# Ver status das Applications no ArgoCD
kubectl get applications -n argocd

# Ver pods de DEV
kubectl get pods -n demo-app-dev

# Ver pods de PRD
kubectl get pods -n demo-app-prd

# Forçar sync manual no ArgoCD
kubectl annotate application demo-app-dev -n argocd argocd.argoproj.io/refresh=normal
kubectl annotate application demo-app-prd -n argocd argocd.argoproj.io/refresh=normal

# Recriar o cluster do zero
kind delete cluster
kind create cluster --config cluster/kind-multinode.yaml --name kind
```

---

## Observações

- O ArgoCD **não gerencia a si mesmo** via Application — os manifests em `cluster/ArgoCD/` devem ser aplicados manualmente com `kubectl apply` após (re)criar o cluster
- O `argocd-cmd-params-cm.yaml` configura o ArgoCD em modo HTTP (`server.insecure: "true"`) para funcionar corretamente com o ingress NGINX sem TLS
- As Applications têm `selfHeal: true` e `prune: true` — qualquer divergência entre Git e cluster é corrigida automaticamente pelo ArgoCD
