# Shared — Baseline, Trazabilidad y PASO 0 para Auditorías

Este documento define el contrato común y el **PASO 0 completo** para todas las skills de auditoría del proyecto. Ninguna skill debe redefinir este contenido.

## Objetivo

Mantener un lenguaje operativo único para:

- contexto histórico
- baseline
- delta real
- working tree
- trazabilidad Git / GitHub
- reportes sin commits automáticos
- ejecución secuencial vía orquestador

En una línea:

> **contexto primero, baseline explícito, delta real, cero commits automáticos**

---

## Input Mínimo Obligatorio

Antes de emitir cualquier hallazgo, revisar SIEMPRE en este orden:

1. **LECCIONES_APRENDIDAS.md** → causas raíz, deuda conocida y convenciones del proyecto
2. **Otros/Info_Auditorias/** → artefactos previos:
    - `baseline_info.txt`
    - `baseline_structure.txt`
    - `baseline_dependencies.txt`
    - `audit_code_*.md`, `audit_architecture_*.md`, `audit_product_*.md`
    - `audit_code_*.json`, `audit_architecture_*.json`, `audit_product_*.json`
    - `Respuesta-audit_code_*.md`, `Respuesta-audit_architecture_*.md`, `Respuesta-audit_product_*.md`
    - `audit_consolidated_*.md` (si existe del orquestador)
    - `audit_consolidated_*.json`
    - `verification_*.md`
3. **Contexto compartido**: `.opencode/audit-context.json` (generado por orquestador)
4. **Estado Git actual**: branch, tracking remoto, commits, working tree, diff contra baseline
5. **Docs locales del framework** cuando un hallazgo dependa de una convención versionada

**Regla:** si existe historial en `Otros/Info_Auditorias/` y no se leyó, la conclusión queda incompleta.

---

## PASO 0 Completo (Ejecutar ANTES de auditar)

**ANTES de comenzar cualquier auditoría, ejecutar estos pasos:**

### 0A — Leer Historial de Auditorías y Respuestas Previas

Objetivo: no reabrir hallazgos ya aceptados como deuda, no reciclar falsos positivos, no perder trazabilidad del roadmap.

```text
1. Leer LECCIONES_APRENDIDAS.md
2. Leer los últimos audit_*.md relevantes (code, architecture, product)
3. Leer las respuestas del desarrollador asociadas (Respuesta-audit_*.md)
4. Leer las últimas verification_*.md si existen
5. Si existe audit_consolidated_*.md, leerlo para contexto global
6. Contrastar hallazgos de otras skills si condicionan el alcance actual
7. Registrar explícitamente qué artefactos previos fueron considerados
```

**Regla:** si existe `Otros/Info_Auditorias/` y no se leyó, la auditoría está incompleta.

### 0B — Verificación de Build y Tests (OBLIGATORIO)

**Antes de emitir CUALQUIER hallazgo, ejecutar:**

```bash
# Si falla, es el hallazgo #1 del reporte consolidado
npm run build 2>&1 | tail -30
BUILD_EXIT=$?

npm test 2>&1 | tail -30
TEST_EXIT=$?

npm run lint 2>&1 | tail -30
LINT_EXIT=$?
```

| Comando | Si falla | Acción |
|---------|----------|--------|
| `npm run build` | Pipeline se detiene | Hallazgo CRIT: "Build roto" en consolidado |
| `npm test` | Se registra | Hallazgo HIGH: "Tests fallando" |
| `npm run lint` | Se registra | Hallazgo MED: "Lint warnings" |

**Regla:** Si el build no compila, no tiene sentido auditar código roto. El pipeline se detiene y el primer hallazgo consolidado es "EL BUILD ESTÁ ROTO".

### 0C — Resolver el Baseline

Resolver baseline con esta prioridad:

1. `Otros/Info_Auditorias/baseline_info.txt`
2. Hash explícito dentro de auditorías o respuestas previas, por ejemplo:
   - `Commit auditado: <hash>`
   - `Snapshot de referencia: <hash>`
3. `HEAD` actual como snapshot lógico si no existe baseline formal
4. Heurística por historial git (`audit\|baseline`) como último recurso

```bash
# Usar script compartido (portable)
source .agents/skills/shared/scripts/resolve-baseline.sh
echo "Baseline: $BASELINE_HASH (fuente: $BASELINE_SOURCE)"
echo "Modo: $DIFF_MODE"
```

**Regla:** si el baseline no viene de `baseline_info.txt`, declarar la fuente en el reporte.

### 0C — Detectar el Modo Real de Comparación

No asumir que todos los cambios están comiteados.

| Escenario | Qué comparar |
|---|---|
| Baseline confiable + commits posteriores + working tree limpio | `BASELINE..HEAD` |
| Baseline confiable + sin commits posteriores + working tree modificado | `git diff BASELINE` |
| Baseline confiable + commits posteriores + working tree modificado | reportar ambos |
| Sin baseline confiable | auditoría full del estado actual + advertencia explícita |

```bash
# El script resolve-baseline.sh ya ejecuta esto
# Verificar adicionalmente:
git status --short --branch
if [ -n "$BASELINE_HASH" ]; then
  git log --oneline "$BASELINE_HASH"..HEAD
  git diff --name-only "$BASELINE_HASH"
fi
```

**Regla:** el reporte debe declarar si se auditó `baseline..HEAD`, working tree vs baseline, repo actual completo, o una combinación.

### 0D — Validar Trazabilidad Git / GitHub

**Hacer commit local NO requiere conexión a GitHub.** GitHub solo importa para `push`, PR o trazabilidad remota.

#### Plano 1 — Git local

```bash
git rev-parse --is-inside-work-tree
git status --short --branch
git remote -v
```

#### Plano 2 — GitHub (`gh`) opcional

```bash
gh auth status
```

Interpretación:

- **Git local OK + `gh` no autenticado** → se puede auditar y comitear localmente
- **Git local OK + `gh` autenticado** → además trazabilidad remota opcional
- **Git local roto** → detenerse, no hay baseline confiable

**Regla:** no bloquear auditoría ni commit local por falta de auth de GitHub.

### 0E — Baseline Commit Formal (OPCIONAL)

Crear commit baseline solo si se cumplen TODAS estas condiciones:

1. El usuario pidió explícitamente máxima trazabilidad con commit baseline
2. No existe ya un baseline confiable suficiente
3. Hay cambios que vale la pena congelar antes de auditar
4. El usuario autorizó el commit de forma explícita

```bash
git add -A
git commit -m "chore(audit): baseline snapshot before [TIPO] audit YYYY-MM-DD HH:MM"
git log -1 --format='%H' HEAD
```

**Reglas críticas:**
- NO asumir commit automático
- NO crear baseline commit si el usuario no lo pidió
- NO confundir `gh auth status` con requisito para commit local
- Si no hay permiso, usar baseline lógico y continuar

### 0F — Generar Archivo de Contexto Baseline (Snapshot Documental)

Crear o actualizar en `Otros/Info_Auditorias/` un snapshot del estado auditado. Sirve aunque no exista commit formal nuevo.

Contenido mínimo:

- baseline hash o snapshot lógico usado
- fuente del baseline
- fecha
- branch actual
- modo de comparación
- si había working tree modificado
- estructura del scope auditado
- dependencias relevantes

### 0G — Archivo de Auditoría (Delegado a Cada Skill)

Cada skill define el nombre y template de su archivo de reporte en su sección **SALIDA**.

Convención de nombres:

| Skill | Patrón |
|---|---|
| software-code-auditor | `audit_code_YYYY-MM-DD_HHMM.md` |
| software-architecture-auditor | `audit_architecture_YYYY-MM-DD_HHMM.md` |
| software-product-auditor | `audit_product_YYYY-MM-DD_HHMM.md` |
| software-audit-orchestrator | `audit_consolidated_YYYY-MM-DD_HHMM.md` |

El contrato MÍNIMO de todo reporte (independientemente del tipo):

- baseline o snapshot usado
- fuente del baseline
- modo de comparación
- artefactos previos leídos
- estado del working tree al inicio
- riesgos no validados por ejecución, si aplica

---

## Convenciones de Interpretación

- deuda aceptada/documentada NO debe reaparecer como "issue nuevo"
- falsos positivos previos deben respetarse salvo evidencia nueva contundente
- working tree modificado también cuenta como realidad verificable
- si un hallazgo depende del framework, contrastar contra docs versionadas instaladas
- hallazgos referidos desde otras skills deben ser contrastados, no ignorados

---

## Modo de Ejecución

### Standalone (una skill invocada individualmente)

La skill ejecuta su PASO 0 completo según este documento y luego su metodología específica.

### Pipeline (vía software-audit-orchestrator)

El orquestador ejecuta el PASO 0 **una sola vez** y pasa el contexto resuelto a cada skill. Las skills deben:
1. **Saltarse el PASO 0** (ya fue ejecutado por el orquestador)
2. **Usar el contexto provisto** (baseline, diff, artefactos previos)
3. **Recibir hallazgos de skills previas** como input contextual

Cada skill indica en su sección **Input Contextual** qué espera recibir del orquestador.

---

## Cómo Usar Este Documento

| Skill | Modo de uso |
|---|---|
| software-code-auditor | Referencia el shared; ejecuta PASO 0 standalone o recibe contexto del orquestador |
| software-architecture-auditor | Ídem |
| software-product-auditor | Ídem |
| software-audit-orchestrator | **Implementa** el PASO 0 una vez y lo provee a las skills del pipeline |
| software-audit-verifier | Usa el shared para validar baseline y delta en verificaciones post-fix |
