# software-code-auditor — Material de Referencia

> Contenido detallado: categorías, reglas, severidades, formatos.
> Consultar bajo demanda durante la auditoría. No cargar completo a menos que sea necesario.

---

## Metodología Detallada

### PASO 0 — Mapa del proyecto

Antes de auditar, construir el mapa mental:
1. Qué archivos exportan qué (componentes, funciones, tipos, constantes)
2. Qué páginas existen y qué componentes usan
3. Cuáles son los archivos de datos y quién los consume
4. Cuáles son las claves del diccionario i18n y cuáles se usan

### PASO 1 — LECCIONES_APRENDIDAS.md (Checklist Prioritario)

LEER primero `LECCIONES_APRENDIDAS.md` en la raíz del proyecto.
Cada regla violada = hallazgo ANTES de continuar.

Además contrastar contra `Otros/Info_Auditorias/` para detectar:
- falsos positivos ya descartados
- deuda aceptada/documentada
- regresiones de fixes previos
- respuestas del desarrollador que requieren validación especial

Si un hallazgo previo ya fue aceptado como deuda o diferido con justificación válida, reportarlo como contexto/persistencia, no como "descubrimiento nuevo".

### PASO 2 — Código Muerto (CRÍTICO — categoría más omitida)

Para cada archivo en `components/`, `data/`, `lib/`, `hooks/`, `types/`:
```
1. Listar qué exporta
2. grep ese export en TODOS los archivos del proyecto
3. Si no aparece en ningún import → código muerto
```
- Función exportada sin importadores → eliminar
- Tipo en `types/index.ts` sin uso → eliminar o documentar
- Archivo de datos sin consumidores → huérfano

### PASO 3 — Auditoría i18n Bidireccional

**3A — Claves usadas en componentes pero inexistentes en JSON**
```
Para cada dict.X.Y.Z o t.X en .tsx/.ts:
  → Verificar que existe en messages/es.json
  → Verificar que existe en messages/en.json
  → Si falta en alguno → error de runtime en producción
```

**3B — Claves en JSON sin uso en componentes (HUÉRFANAS)**
```
Para cada clave de primer nivel en messages/es.json:
  → Buscar referencias en todos los .tsx y .ts
  → Si no se usa → clave huérfana = bug de localización potencial
```

**3C — Asimetría entre es.json y en.json**
```
Los dos JSON deben tener exactamente las mismas claves.
Cualquier diferencia → bug de localización.
```

### PASO 4 — Consistencia del Grafo de Imports

```
Para cada archivo refactorizado recientemente:
  → Verificar que todos los imports resuelven a exportaciones existentes
  → Si importa { Tipo } desde @/data/algo pero fue movido a @/types → import roto
  → Verificar especialmente: types/index.ts, data/faq.ts, lib/faq-matcher.ts, lib/schemas/contact.ts
```

### PASO 5 — Consistencia de Datos Entre Archivos

```
FAQ vs catálogo: tamaños en data/faq.ts deben coincidir con presentation de data/products.ts
Datos de contacto: ningún archivo fuera de lib/config.ts debe tener teléfono o email hardcodeado
presentationOrder: dentro de cada line, valores 1, 2, 3... sin gaps ni duplicados
```

### PASO 6 — Schemas Zod y Localización

```
Para cada schema Zod:
  → ¿Tiene mensajes de error hardcodeados en español?
  → ¿Ese schema se usa en un componente cliente renderizado en múltiples idiomas?
  → Si sí → bug de localización. Debe ser factory function que acepte msgs del diccionario
```

---

## Las 8 Categorías de Auditoría

### 🟥 CAT-1 — Seguridad (OWASP Top 10)

| ID | Regla | Severidad |
|----|-------|-----------|
| SEC-01 | NO loguear PII (nombre, email, teléfono) en console.log en producción | CRITICAL |
| SEC-02 | Toda API route debe validar body con Zod ANTES de procesarlo | CRITICAL |
| SEC-03 | API routes públicas deben tener rate limiting o documentar ausencia | HIGH |
| SEC-04 | Variables sensibles NUNCA con prefijo NEXT_PUBLIC_ | CRITICAL |
| SEC-05 | Links externos con `target="_blank"` deben incluir `rel="noopener noreferrer"` | MED |
| SEC-06 | Datos de usuario escapados antes de interpolar en HTML (XSS) | CRITICAL |
| SEC-07 | Datos de contacto vienen de SITE_CONFIG, no hardcodeados | HIGH |
| SEC-08 | iframes externos deben tener `sandbox` o `referrerPolicy` | MED |

### 🟠 CAT-2 — Bugs y Correctitud

| ID | Regla | Severidad |
|----|-------|-----------|
| BUG-01 | Todo setInterval/setTimeout debe cleanup en useEffect | HIGH |
| BUG-02 | IDs de setTimeout en ref para poder cancelarlos (clearTimeout) | MED |
| BUG-03 | Valores server/client idénticos en primer render (no hydration mismatch) | HIGH |
| BUG-04 | Date.now() dentro de componentes debe estar en useEffect o useMemo | MED |
| BUG-05 | Arrays de dependencias de useEffect exhaustivos | MED |
| BUG-06 | catch vacío o solo console.error debe retornar estado de error al usuario | HIGH |
| BUG-07 | Textos de contenido en español (sin mezcla accidental de inglés) | MED |
| BUG-08 | Datos mock sin errores tipográficos ni whitespace accidental | LOW |
| BUG-09 | Función recibe parámetro que NO usa en TODAS sus ramas → bug silencioso | HIGH |

### 🔵 CAT-3 — Next.js App Router

| ID | Regla | Severidad |
|----|-------|-----------|
| NEXT-01 | "use client" solo si hay hooks, eventos browser, o APIs de cliente | HIGH |
| NEXT-02 | Componentes compartidos solo en app/[lang]/layout.tsx | MED |
| NEXT-03 | Solo next/image, nunca `<img>` nativo | HIGH |
| NEXT-04 | Imágenes above-the-fold con priority={true} | MED |
| NEXT-05 | Imágenes en grids con sizes apropiado | MED |
| NEXT-06 | sitemap.ts usa fecha fija, no new Date() sin args | MED |
| NEXT-07 | robots.txt existe en /public/ | LOW |
| NEXT-08 | JSON-LD (Organization schema) en layout.tsx | MED |
| NEXT-09 | API routes retornan códigos HTTP correctos (200, 400, 500) | HIGH |
| NEXT-10 | NEXT_PUBLIC_* solo para datos NO sensibles | HIGH |
| NEXT-11 | proxy.ts en raíz con función exportada proxy. middleware.ts es DEPRECADA | HIGH |

### 🟡 CAT-4 — TypeScript

| ID | Regla | Severidad |
|----|-------|-----------|
| TS-01 | Prohibido any explícito o implícito | HIGH |
| TS-02 | Tipos compartidos en types/index.ts, no en componentes ni data/ | MED |
| TS-03 | Union types numéricos estrictos cuando el rango es conocido | LOW |
| TS-04 | Props opcionales no usadas por ningún padre → eliminar | MED |
| TS-05 | z.infer reusa tipos de types/index.ts si ya existen | LOW |
| TS-06 | Imports de tipos movidos a otro archivo → import roto silencioso | HIGH |

### 🟢 CAT-5 — Rendimiento

| ID | Regla | Severidad |
|----|-------|-----------|
| PERF-01 | Componentes con solo whileInView y dict → dict como prop, no via Context | MED |
| PERF-02 | Valores computados costosos en useMemo | MED |
| PERF-03 | Hero con priority={true} y sizes correctos | MED |
| PERF-04 | Carruseles con autoplay pausan con IntersectionObserver | LOW |
| PERF-05 | No crear objetos/arrays nuevos en cada render sin useMemo | MED |
| PERF-06 | Usar m en lugar de motion (LazyMotion ya en DictionaryProvider) | MED |
| PERF-07 | Componentes con useSearchParams, useState server-derived, o cookies → verificar hydration en navegador | HIGH |

### 🔷 CAT-6 — Accesibilidad (WCAG AA)

| ID | Regla | Severidad |
|----|-------|-----------|
| A11Y-01 | Botones sin texto visible tienen aria-label (del diccionario si multilenguaje) | HIGH |
| A11Y-02 | alt descriptivo, en el idioma de la interfaz | MED |
| A11Y-03 | Elementos interactivos son `<button>` o `<a>`, no `<div>` | HIGH |
| A11Y-04 | Contraste WCAG AA (ratio mínimo 4.5:1 para texto normal) | MED |
| A11Y-05 | iframes con title | MED |
| A11Y-06 | Formularios con label asociado a cada input | MED |
| A11Y-07 | aria-label hardcodeados en español en componentes /en/ → bug de localización | HIGH |

### 🟣 CAT-7 — Calidad de Código y Deuda Técnica

| ID | Regla | Severidad |
|----|-------|-----------|
| DT-01 | TODOs documentados con fecha estimada o ticket | LOW |
| DT-02 | Wrappers sin lógica eliminados | LOW |
| DT-03 | Datos de contacto en SITE_CONFIG, no hardcodeados | HIGH |
| DT-04 | No href="#" sin documentar | MED |
| DT-05 | Teléfono/email en un solo lugar (lib/config.ts) | MED |
| DT-06 | Props declaradas no usadas por ningún padre → eliminar | MED |
| DT-07 | Código muerto → ver PASO 2 | HIGH |

### 🩷 CAT-8 — UX y Contenido

| ID | Regla | Severidad |
|----|-------|-----------|
| UX-01 | Estados toast/error tienen auto-cierre (no visibles indefinidamente) | MED |
| UX-02 | CTAs de carruseles redirigen a URL contextual, no genérica | MED |
| UX-03 | Countdown timer sin flash de 00:00:00 en hydration | MED |
| UX-04 | Sin errores ortográficos ni palabras en idioma incorrecto | LOW |
| UX-05 | Respuestas FAQ verificadas contra catálogo real (tamaños, precios, datos) | HIGH |

---

## Escala de Severidad

| Nivel | Código | Descripción |
|-------|--------|-------------|
| Crítico | 🔴 CRIT | Vulnerabilidad explotable o bug que rompe la app en producción |
| Alto | 🟠 HIGH | Bug grave o deuda técnica con impacto directo en el usuario |
| Medio | 🟡 MED | Mala práctica, código frágil o inconsistencia arquitectural |
| Bajo | 🟢 LOW | Mejora de calidad, limpieza o convención no seguida |
| Info | ℹ️ INFO | Observación sin impacto inmediato |

## Formato de Hallazgo

```
[SEVERIDAD] ID-REGLA — Archivo:línea
Síntoma: qué ve el usuario o qué falla
Causa raíz: por qué ocurrió
Solución: cambio exacto a hacer
```

Al finalizar:
1. Tabla resumen con conteo por severidad
2. Top 5 issues ordenadas por impacto real en el usuario
3. Lista de archivos SIN hallazgos (confirmados limpios — para no revisarlos dos veces)

## Schema JSON de Hallazgos

```json
{
  "meta": {
    "skill": "software-code-auditor",
    "version": "1.3",
    "date": "YYYY-MM-DDTHH:MM:SS",
    "baseline": "<hash>",
    "mode": "full | delta",
    "duration_minutes": <int>
  },
  "findings": [
    {
      "id": "SEC-01",
      "severity": "CRIT | HIGH | MED | LOW | INFO",
      "category": "SEC | BUG | NEXT | TS | PERF | A11Y | DT | UX",
      "files": [{"path": "ruta/archivo.ts", "lines": [1, 2, 3]}],
      "title": "Resumen corto",
      "description": "Descripción detallada",
      "recommendation": "Cambio exacto a hacer",
      "cross_skill": [],
      "dependencies": []
    }
  ],
  "stats": {
    "total": <int>,
    "crit": <int>,
    "high": <int>,
    "med": <int>,
    "low": <int>,
    "by_category": { "SEC": 0, "BUG": 0, "NEXT": 0, "TS": 0, "PERF": 0, "A11Y": 0, "DT": 0, "UX": 0 }
  },
  "files_clean": ["ruta/libre/de/hallazgos.ts"],
  "unvalidated_risks": ["descripción de riesgo no validado"]
}
```

## Patrones Correctos del Proyecto

```typescript
// Framer Motion — usar m, no motion
import { m, AnimatePresence } from "framer-motion";

// i18n — dict como prop en Server Components
export function Componente({ dict }: { dict: Dictionary }) { ... }

// Datos de contacto — siempre desde SITE_CONFIG
import { SITE_CONFIG } from "@/lib/config";

// Zod con i18n — factory function
createContactSchema(dict.contact.validation)

// Proxy (Next.js 16) — función exportada proxy en proxy.ts
export default function proxy(request: Request)
```

## Recursos

- **LECCIONES_APRENDIDAS.md** → Causas raíz de errores anteriores (checklist prioritario)
- **messages/es.json** y **messages/en.json** → Verificar simetría de claves i18n
- **types/index.ts** → Tipos compartidos del proyecto
- **lib/config.ts** → Datos de contacto centralizados
