---
name: safe-refactor-tdd
description: >
  Refactorizacion segura guiada por TDD, pruebas de caracterizacion y QA incremental
  para proyectos web cercanos a produccion. Orquesta auditorias existentes, define
  red de seguridad automatizada y permite refactorizar solo cuando el comportamiento
  esta protegido. Trigger: "safe refactor", "refactor seguro", "TDD", "pruebas de
  caracterizacion", "red de seguridad", "cubrir con tests", "refactorizar con tests",
  "pruebas unitarias", "pruebas de integracion", "pruebas end-to-end", "E2E".
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

## When to Use

- El usuario pide aplicar TDD o modelar una estrategia de pruebas.
- El usuario pide refactorizar sin romper comportamiento existente.
- El usuario pide crear una red de seguridad antes de cambios.
- El usuario pide cubrir modulos con pruebas unitarias, integracion o E2E.
- El proyecto esta cerca de produccion y se requiere estabilizacion incremental.
- Hay hallazgos previos de auditoria que necesitan fixes/refactors seguros.

## Rol de Esta Skill

Esta skill es una **orquestadora de refactorizacion segura**, no una auditoria full nueva.

Debe coordinar:

- `software-code-auditor` para detectar bugs, seguridad, i18n y deuda tecnica de codigo.
- `software-architecture-auditor` para detectar riesgos estructurales, rendering, performance y stack.
- `software-audit-verifier` para verificar despues de cambios si hubo fixes reales, parciales o regresiones.
- `.agents/skills/shared-audit-baseline-traceability.md` para baseline, delta real y trazabilidad.
- `Otros/TDD-Model.txt` como fuente metodologica principal.

En una linea:

> **proteger comportamiento primero, refactorizar despues, verificar siempre**.

## Principios Criticos

1. El objetivo NO es reescribir el sistema.
2. El objetivo inicial NO es optimizar codigo.
3. El primer objetivo es proteger comportamiento actual con pruebas de caracterizacion.
4. No cubrir todo el proyecto al mismo tiempo.
5. Trabajar por modulos pequenos, con riesgo y alcance explicitos.
6. No refactorizar sin cobertura previa suficiente.
7. No avanzar al siguiente modulo si existen pruebas fallando.
8. No cambiar diseno visual, funcionalidades de usuario o contratos externos salvo pedido explicito.
9. No introducir dependencias nuevas sin justificar valor, costo y alternativa.
10. No hacer commits automaticos.

## Contrato Compartido Obligatorio

Antes de seleccionar modulo, escribir tests o refactorizar, aplicar:

- `.agents/skills/shared-audit-baseline-traceability.md`

Input minimo obligatorio:

1. Leer `LECCIONES_APRENDIDAS.md` si existe.
2. Leer artefactos relevantes en `Otros/Info_Auditorias/`.
3. Resolver baseline o snapshot logico.
4. Detectar delta real: commits, working tree o ambos.
5. Declarar riesgos no validados por ejecucion.
6. Leer documentacion local/versionada de Next.js cuando se toque una convencion del framework.

Regla: si existe historial de auditorias y no se leyo, el trabajo esta incompleto.

## Observacion Operativa De Activacion

Si el loader de Skills no reconoce `safe-refactor-tdd` pero el archivo existe en disco:

1. Leer `.agents/skills/safe-refactor-tdd/SKILL.md` directamente.
2. Ejecutar esta Skill siguiendo el contenido del archivo leido.
3. Registrar la discrepancia en el reporte bajo `Observacion Operativa`.
4. No bloquear el trabajo solo por falta de refresco del loader.

Esto puede ocurrir en la misma sesion en que la Skill fue creada o registrada.

## Relacion con Skills Existentes

| Momento | Skill relacionada | Uso correcto |
|---|---|---|
| Antes de decidir modulo | `software-code-auditor` | Tomar hallazgos de bugs, seguridad, i18n y deuda tecnica como candidatos de cobertura/refactor |
| Antes de tocar arquitectura | `software-architecture-auditor` | Tomar riesgos de rendering, bundle, data fetching y estructura como candidatos de cobertura/refactor |
| Durante este flujo | `safe-refactor-tdd` | Crear tests de caracterizacion, aplicar RED/GREEN/REFACTOR y limitar alcance |
| Despues del cambio | `software-audit-verifier` | Verificar delta, persistencias, parciales, regresiones y nuevos issues |

No duplicar reglas de auditoria. Si hace falta una auditoria full, usar la skill correspondiente.

## Fase 1 - Analisis Inicial y Mapa de Riesgos

Antes de escribir pruebas:

1. Analizar estructura del modulo objetivo.
2. Identificar dependencias directas e indirectas.
3. Identificar APIs, formularios, rutas, servicios, hooks, estados, CMS, DB o integraciones externas involucradas.
4. Detectar complejidad, acoplamiento, duplicacion y dificultad de testeo.
5. Clasificar prioridad: ALTA, MEDIA, BAJA.
6. Explicar que se debe probar primero y que NO debe tocarse inicialmente.

### Matriz de Riesgo Requerida

| Criterio | Bajo | Medio | Alto |
|---|---|---|---|
| Criticidad | No bloquea flujos | Afecta experiencia parcial | Afecta negocio, seguridad, datos o conversion |
| Complejidad | Funcion pura o UI simple | Varias dependencias internas | APIs, estado, IO, terceros o flujo multi-paso |
| Impacto usuario | Poco visible | Visible pero recuperable | Rompe tarea principal o confianza |
| Probabilidad de fallo | Codigo estable/simple | Cambios recientes o ramas condicionales | Historial de bugs, acoplamiento o efectos laterales |
| Dificultad de test | Unitario directo | Requiere mocks/fixtures | Requiere navegador, red, DB, CMS o auth |
| Dificultad de refactor | Cambio local | Varias referencias | Contratos publicos o comportamiento distribuido |

### Priorizacion del Proyecto

Alta prioridad:

- autenticacion y autorizacion si existen;
- formularios;
- validaciones;
- manejo de errores;
- navegacion;
- API routes;
- persistencia;
- logica de negocio;
- seguridad;
- estados globales;
- procesos criticos del cliente.

Media prioridad:

- componentes reutilizables;
- tablas;
- filtros;
- busquedas;
- paginacion;
- modales y drawers.

Baja prioridad:

- estilos visuales menores;
- componentes estaticos;
- texto plano;
- animaciones simples.

## Fase 2 - Construccion de Red de Seguridad

Primero crear pruebas de caracterizacion para capturar el comportamiento actual.

Validar:

- formularios;
- navegacion;
- renderizado;
- respuestas API;
- validaciones;
- manejo de errores;
- flujos criticos de usuario;
- integraciones internas relevantes.

Regla: si el comportamiento actual no esta protegido, no refactorizar.

## Modo Piloto / Sin Tooling

En la primera ejecucion, o cuando el proyecto no tiene infraestructura de tests:

1. No instalar dependencias automaticamente.
2. No escribir tests a ciegas.
3. No refactorizar codigo productivo.
4. Ejecutar solo diagnostico, matriz de riesgo, estrategia de pruebas y reporte.
5. Recomendar tooling minimo por capa: unitarias, integracion y E2E.
6. Pedir decision explicita antes de agregar dependencias o scripts.

Este modo sirve para validar que el flujo es correcto antes de cambiar el proyecto.

## Fase 3 - Estrategia de Pruebas

Usar tres niveles de prueba. Elegir el nivel por riesgo, no por costumbre.

### Prioridad 1 - End-to-End (E2E)

Objetivo: validar lo que hace el usuario real en el navegador.

Usar para:

- navegacion critica;
- formularios principales;
- login/registro/recuperacion si existen;
- envio de datos;
- consumo visible de APIs;
- permisos y cierres de sesion si existen;
- dashboards o flujos principales si existen;
- flujos criticos del cliente.

E2E debe cubrir el camino feliz y al menos un error importante cuando el flujo sea critico.

No usar E2E para detalles internos que se validan mejor con integracion o unit tests.

### Prioridad 2 - Pruebas de Integracion

Objetivo: validar flujos internos entre piezas reales o semi-reales.

Usar para:

- componente + hook;
- formulario + schema;
- API route + validacion;
- servicio + cliente mockeado;
- estado global + UI;
- middleware/proxy + requests simuladas;
- base de datos/CMS mockeados o sandbox si corresponde.

Detectar:

- errores de sincronizacion;
- contratos rotos;
- dependencias fragiles;
- fallos en comunicacion entre capas.

### Prioridad 3 - Pruebas Unitarias

Objetivo: validar funciones, componentes simples y logica deterministica con feedback rapido.

Usar para:

- funciones puras;
- validadores;
- schemas Zod;
- sanitizacion;
- helpers;
- transformaciones de datos;
- hooks reutilizables con logica;
- componentes con ramas condicionales relevantes.

No escribir pruebas unitarias triviales sin valor real.

No testear implementacion interna si el comportamiento publico queda mejor cubierto en integracion.

## Fase 4 - Ciclo RED/GREEN/REFACTOR

Trabajar siempre con este ciclo:

### RED

- Crear una prueba que falle o demuestre una brecha de comportamiento.
- Si es caracterizacion, documentar el comportamiento actual esperado antes de cambiarlo.
- Confirmar que la prueba falla por la razon correcta cuando sea viable.

### GREEN

- Implementar el cambio minimo para pasar la prueba.
- Evitar mejoras laterales.
- Mantener contratos y comportamiento externo.

### REFACTOR

- Mejorar legibilidad, modularidad, nombres, acoplamiento o rendimiento.
- Mantener todas las pruebas pasando.
- No cambiar comportamiento funcional ni visual sin autorizacion.

## Gate Antes de Refactorizar

Antes de refactorizar, responder:

1. Que problema tecnico se encontro.
2. Que riesgo existe si no se corrige.
3. Que archivos seran afectados.
4. Que pruebas protegen el comportamiento actual.
5. Que mejora concreta se espera.
6. Que impacto podria existir.
7. Como revertir o aislar el cambio si falla.

Si alguna respuesta no esta clara, no refactorizar todavia.

## Flujo Operativo por Modulo

Para cada modulo:

1. Leer contexto historico y baseline.
2. Analizar modulo y dependencias.
3. Crear matriz de riesgo.
4. Definir estrategia de tests: unitarias, integracion, E2E.
5. Crear pruebas de caracterizacion.
6. Ejecutar validaciones relevantes.
7. Refactorizar solo si es seguro.
8. Ejecutar validaciones nuevamente.
9. Guardar reporte de resultados.
10. Solicitar o ejecutar verificacion post-cambio con criterios de `software-audit-verifier`.

## Tooling Esperado

No asumir herramientas si el proyecto aun no las tiene.

Si no existe stack de testing:

1. Detectar scripts y dependencias actuales.
2. Proponer tooling minimo por capa.
3. Justificar cada dependencia.
4. Instalar/configurar solo si el usuario lo pidio o la tarea lo requiere claramente.

Guia preferida para Next.js/React:

- E2E: Playwright.
- Unitarias e integracion: Vitest.
- Componentes React: Testing Library cuando aporte valor.
- API/MSW: mocks o MSW cuando haya flujos HTTP relevantes.

Regla del proyecto: no ejecutar build despues de cambios.

## Tooling Readiness Gate

Antes de entrar en RED/GREEN/REFACTOR, verificar:

| Capa | Senal requerida |
|---|---|
| Unitarias | existe runner (`vitest`, `jest` u otro), script `test` o comando documentado |
| Integracion | existe forma de mockear dependencias externas o entorno controlado |
| E2E | existe runner navegador (`playwright`, `cypress` u otro), script/config o decision explicita para crearlo |
| Validacion base | existe al menos `lint`, typecheck o comando equivalente |

Si falta tooling para la capa necesaria, detener implementacion y reportar:

- tooling faltante;
- dependencia sugerida;
- tradeoff;
- primer modulo recomendado;
- comando que se agregaria.

No confundir estrategia ideal con ejecucion posible: a nivel proyecto los flujos E2E criticos son prioridad alta, pero dentro de un modulo sin tooling se empieza por preparar la infraestructura minima segura.

## Validaciones Permitidas y Reporte

Ejecutar solo validaciones relevantes al scope:

- `npm run lint` si existe y el cambio toca codigo lintable.
- `npm run test` si existe.
- `npm run test:e2e` si existe y el cambio afecta flujos navegador.
- comandos especificos de test por archivo/modulo si existen.

Si no se puede ejecutar una validacion, reportar:

- comando no disponible;
- dependencia faltante;
- limitacion del entorno;
- riesgo residual.

## Formato de Reporte

Guardar reportes significativos en:

```text
Otros/Info_Auditorias/safe_refactor_tdd_YYYYMMDD_HHMM.md
```

Template minimo:

```markdown
# Safe Refactor TDD - [FECHA]

## Metadatos
- Baseline / Snapshot: [hash o descripcion]
- Fuente del baseline: [baseline_info|auditoria previa|HEAD actual|sin baseline formal]
- Modo de comparacion: [baseline..HEAD|working tree vs baseline|repo actual completo|ambos]
- Artefactos previos leidos: [lista]
- Modulo objetivo: [ruta/s]

## Matriz de Riesgo
| Modulo | Prioridad | Criticidad | Complejidad | Impacto usuario | Probabilidad fallo | Dificultad test | Dificultad refactor |
|---|---|---|---|---|---|---|---|

## Estado de Tooling
- Tests existentes: [si/no]
- Runner unit/integration: [si/no]
- Runner E2E: [si/no]
- Scripts disponibles: [lista]
- Bloqueos: [lista]

## Estrategia de Pruebas
- Unitarias: [que cubren y por que]
- Integracion: [que flujo interno cubren y por que]
- E2E: [que comportamiento de usuario cubren y por que]

## Ciclo RED/GREEN/REFACTOR
- RED: [pruebas creadas/fallo esperado]
- GREEN: [cambio minimo]
- REFACTOR: [mejora aplicada o no aplicada]

## Validaciones Ejecutadas
- [comando] - [resultado]

## Resultado
- Comportamiento protegido: [si/no/parcial]
- Refactor aplicado: [si/no]
- Riesgos residuales: [lista]
- Requiere verificacion post-auditoria: [si/no]
```

## Red Lines

```text
NO reescribir el sistema completo.
NO refactorizar sin pruebas previas suficientes.
NO cambiar comportamiento funcional durante caracterizacion.
NO cambiar diseno visual innecesariamente.
NO introducir dependencias innecesarias.
NO avanzar con tests fallando.
NO duplicar auditorias existentes.
NO cerrar un refactor sin verificacion y reporte de riesgos residuales.
NO hacer commits automaticos.
```

## Recursos

- `Otros/TDD-Model.txt` - metodologia base de TDD incremental y refactorizacion segura.
- `.agents/skills/shared-audit-baseline-traceability.md` - contrato comun de baseline y trazabilidad.
- `.agents/skills/software-code-auditor/SKILL.md` - fuente de hallazgos de codigo, bugs, seguridad e i18n.
- `.agents/skills/software-architecture-auditor/SKILL.md` - fuente de hallazgos arquitecturales y roadmap.
- `.agents/skills/software-audit-verifier/SKILL.md` - verificacion post-cambio.
- `package.json` - scripts y tooling de testing disponible.
- `node_modules/next/dist/docs/` - documentacion local/versionada de Next.js antes de tocar convenciones del framework.
