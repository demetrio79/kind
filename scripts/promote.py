#!/usr/bin/env python3
import os

dev_path = "apps/demo-app/dev/configmap.yaml"
prd_path = "apps/demo-app/prd/configmap.yaml"

with open(dev_path, "r", encoding="utf-8") as f:
    dev_content = f.read()

prd_content = dev_content
prd_content = prd_content.replace("demo-app-dev", "demo-app-prd")
prd_content = prd_content.replace("DEV", "PRODUÇÃO")
prd_content = prd_content.replace("Ambiente de Desenvolvimento", "Ambiente de PRODUÇÃO")
prd_content = prd_content.replace("dev.local", "prd.local")
prd_content = prd_content.replace("dev.172.18.0.2.nip.io", "prd.172.18.0.2.nip.io")
prd_content = prd_content.replace("#eab308", "#10b981")
prd_content = prd_content.replace("#f1fa8c", "#34d399")
prd_content = prd_content.replace("#1e1e2e", "#022c22")
prd_content = prd_content.replace("#282a36", "#064e3b")

with open(prd_path, "w", encoding="utf-8") as f:
    f.write(prd_content)

print("Promoção concluída: apps/demo-app/prd/configmap.yaml atualizado com sucesso!")
