# software-audit-verifier — Material de Referencia

---

## Principios Críticos

1. **Esto NO es una auditoría full nueva.** Es verificación delta contra un baseline.
2. **Verificá estado real del repo, no solo commits.** Working tree modificado también cuenta.
3. **Leé SIEMPRE la respuesta del desarrollador** antes de concluir estados.
4. **No confundas "archivo no cambiado" con "hallazgo irrelevante".**
5. **No marques como RESUELTO un fix cosmético** si la causa raíz sigue abierta.
6. **Toda conclusión debe tener evidencia verificable**: diff, grep, lectura actual.
7. **Si un fix toca convenciones del framework**, contrastar contra docs versionadas.

## Metodología Detallada

### PASO 0 — Verificación documental del framework

Si el fix toca: layouts, metadata, routing, i18n, proxy/middleware, file conventions.

Verificar contra `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/`.

### PASO 1 — Resolver baseline real

```
1. baseline_info.txt → BASELINE_COMMIT
2. audit_consolidated_*.json → meta.baseline
3. audit_*.md → "Baseline / Snapshot: <hash>"
4. HEAD como snapshot lógico
```

### PASO 2 — Mapear hallazgos previos

Cargar: `audit_consolidated_latest.json` (o .md si no hay JSON).
Para cada hallazgo: ID, severidad, archivos, estado esperado, commits asociados.

### PASO 3 — Verificar cada hallazgo

```bash
# Para hallazgos de código:
git log --oneline --all | grep -i "fix.*SEC-01\|fix.*BUG-02"
git diff BASELINE_HASH..HEAD -- archivo-afectado.ts
grep -r "patron-buscado" archivo-afectado.ts

# Para hallazgos de producto:
grep -r "texto-esperado" components/ app/
grep -r "aria-label" components/
```

### PASO 4 — Buscar regresiones

Para cada archivo modificado por fixes:
- ¿Nuevos imports rotos?
- ¿Funcionalidades eliminadas?
- ¿Nuevos hallazgos en las 8 categorías?

### PASO 5 — Formato de reporte

```markdown
## Tabla de Verificación
| ID | Severidad | Estado Original | Respuesta Dev | Estado Real | Evidencia |
|---|---|---|---|---|---|

## Regresiones
- [REGRESIÓN] ...

## Resumen
- ✅ Resueltos: N
- ⚠️ Parciales: N
- ❌ Persistentes: N
- 🔄 Regresiones: N
- ⏸️ Diferidos: N
```

## Estados de Verificación

| Estado | Significado |
|---|---|
| ✅ RESUELTO | Fix verificado: diff, grep, o lectura confirman |
| ⚠️ PARCIAL | Parte del fix aplicado, parte pendiente |
| ❌ PERSISTENTE | Sin cambios desde baseline |
| 🔄 REGRESIÓN | Fix intentado pero introdujo nuevo problema |
| ⏸️ DIFERIDO | Deuda aceptada documentada |
| ❓ NO VERIFICABLE | Requiere build/test/runtime para confirmar |
