# software-architecture-auditor — Material de Referencia

> Contenido detallado: checklists por paso, formato de hallazgo, preguntas de seguimiento.
> Consultar bajo demanda durante la auditoría.

---

## Metodología Detallada

### PASO 1 — Inventario Tecnológico

Leer `package.json` completo y listar:
```
Framework principal y versión
Librerías de UI y animación (con tamaño estimado de bundle)
Librerías de formularios y validación
CMS y cliente de datos
Herramientas de análisis y terceros
Dependencias de desarrollo
```

Para cada dependencia clave, evaluar:
1. ¿Es la versión más reciente estable?
2. ¿Tiene alternativas más livianas que cumplan el mismo rol?
3. ¿Se justifica su presencia dado el uso actual en el código?

### PASO 2 — Análisis de Estrategia de Rendering

Mapear cada ruta del proyecto con su estrategia:

```
app/[lang]/page.tsx              → SSR / ISR / SSG / CSR?
app/[lang]/productos/page.tsx    → SSR / ISR / SSG / CSR?
app/[lang]/nosotros/page.tsx     → SSR / ISR / SSG / CSR?
app/[lang]/contacto/page.tsx     → SSR / ISR / SSG / CSR?
app/[lang]/terminos/page.tsx     → SSR / ISR / SSG / CSR?
app/[lang]/politicas/page.tsx    → SSR / ISR / SSG / CSR?
app/[lang]/instagram/page.tsx    → SSR / ISR / SSG / CSR?
app/[lang]/facebook/page.tsx     → SSR / ISR / SSG / CSR?
app/[lang]/tiktok/page.tsx       → SSR / ISR / SSG / CSR?
app/admin/**/*                   → SSR / ISR / SSG / CSR?
```

Para cada ruta, determinar:
- ¿Necesita datos dinámicos en runtime? ¿O puede ser estática?
- ¿Tiene `export const dynamic` configurado? ¿Debería?
- ¿El `revalidate` es el correcto para la frecuencia de cambio del contenido?
- ¿Hay alguna ruta que debería ser `force-static` pero no lo es?
- ¿El proyecto podría beneficiarse de `output: 'export'` (static export)?

### PASO 3 — Análisis de Server Components vs Client Components

Para CADA componente del proyecto, clasificar:
- **RSC (Server Component)**: puede renderizar sin JS en el cliente
- **CC necesario**: usa hooks, eventos, browser APIs — DEBE ser "use client"
- **CC innecesario**: es "use client" solo por herencia o por Context — candidato a convertir

Preguntas específicas a responder:
1. ¿Cuántos componentes son "use client" innecesariamente?
2. ¿El patrón de Context (DictionaryProvider) es la mejor opción para i18n?
3. ¿Hay componentes que podrían aplicar el patrón "Server Component shell + Client island"?

Verificar:
- `m` (no `motion`) en todos los componentes
- `dict` como prop donde corresponde, no via Context

### PASO 4 — Análisis de Bundle y JavaScript

**4A — Dependencias pesadas y alternativas:**
```
framer-motion    → ¿LazyMotion + domAnimation correctamente?
react-hook-form  → ¿Justificado para un solo formulario?
zod              → ¿En bundle del cliente? Debería ser solo servidor
@sanity/client   → ¿Importado en el cliente? Debería ser solo Server Components
resend           → ¿Solo API route?
```

**4B — Code splitting:**
- ¿Rutas que se beneficiarían de `next/dynamic` con lazy loading?
- ¿HeroCarousel se carga eagerly en todas las páginas?
- ¿Imports globales que deberían ser por-ruta?

**4C — Top 5 imports más pesados del proyecto**

### PASO 5 — Data Fetching

**Sanity CMS (si aplica):**
- Queries optimizadas (solo campos necesarios)
- `{ next: { revalidate: N } }` correcto en cada fetch
- `useCdn: true` vs API directo según caso
- Queries combinables para reducir round-trips

**Diccionario i18n:**
- `getDictionary` con `React.cache()` para deduplicar
- Claves huérfanas en JSONs
- Tamaño total razonable

**Datos estáticos (`data/*.ts`):**
- Importados en "use client" (aumentan bundle)?
- Deberían estar en CMS en lugar de .ts?

### PASO 6 — Imágenes y Media

- ¿Todas usan `next/image`? (ningún `<img>` nativo)
- Above-the-fold con `priority` y `loading="eager"`?
- `sizes` correctos para cada contexto?
- ¿Formato WebP/AVIF configurado?
- `quality` reducido donde aplica?
- Archivos >500KB en `/public/imgs/`?

### PASO 7 — SEO y Metadata

- ¿Cada página tiene `generateMetadata` con title, description, og:tags?
- ¿Root layout tiene metadata export como fallback?
- ¿Sitemap incluye todas las rutas con prioridades correctas?
- ¿JSON-LD (Organization schema) presente y completo?
- ¿robots.txt configurado correctamente?
- ¿URLs canonical configuradas?
- ¿`lang` del HTML refleja el idioma actual?

### PASO 8 — Arquitectura i18n

- ¿Patrón `app/[lang]/` con DictionaryProvider Context es el más eficiente?
- ¿Alternativas más livianas? (next-intl, next-i18next)
- ¿Tamaño de JSONs aceptable?
- ¿Claves que deberían venir de CMS en lugar de JSONs?
- ¿LanguageSwitcher funciona en todas las rutas?

### PASO 9 — Accesibilidad Estructural

- Jerarquía headings (h1→h2→h3) semánticamente correcta
- Orden de tab-focus lógico
- Elementos interactivos con keyboard support
- Funciona con JS deshabilitado (graceful degradation)
- Colores cumplen WCAG AA

### PASO 10 — Estructura del Proyecto

- Separación clara entre `components/ui/`, `components/sections/`, `components/layout/`
- Componentes en carpeta correcta
- `lib/` bien organizado
- Separación datos estáticos (`data/`) vs CMS
- Configuración TypeScript optimizada

---

## Formato de Reporte

### Para cada hallazgo:
```
[TIPO] Área → Descripción específica
Estado actual: qué hay hoy
Problema: por qué es subóptimo
Alternativa: qué se podría hacer en cambio
Impacto: Alto / Medio / Bajo
Esfuerzo: Alto / Medio / Bajo
```

**Tipos:** ARQUITECTURA | PERFORMANCE | BUNDLE | RENDERING | I18N | SEO | DATOS | ESTRUCTURA

### Resumen final:
1. Tabla de hallazgos por área con conteo y severidad
2. Top 5 mejoras de mayor impacto/menor esfuerzo (quick wins)
3. Roadmap sugerido en 3 fases

---

## Schema JSON de Hallazgos

Mismo schema que software-code-auditor (REFERENCE.md). Campos específicos:
- `category` usa: ARQUITECTURA | PERFORMANCE | BUNDLE | RENDERING | I18N | SEO | DATOS | ESTRUCTURA
- Campos adicionales: `impact`, `effort`

---

## Escala de Severidad (Arquitectura)

| Nivel | Código | Descripción |
|-------|--------|-------------|
| Crítico | 🔴 CRIT | Decisión arquitectural que compromete seguridad o rendimiento de forma explotable |
| Alto | 🟠 HIGH | Deuda técnica con impacto directo en performance o mantenibilidad |
| Medio | 🟡 MED | Subóptimo pero no bloqueante — mejora con esfuerzo moderado |
| Bajo | 🟢 LOW | Refactor incremental que mejora limpieza sin urgencia |
| Info | ℹ️ INFO | Observación estratégica sin impacto inmediato |

---

## Preguntas de Seguimiento

1. ¿Los quick wins de auditorías anteriores fueron aplicados?
2. ¿La deuda técnica identificada creció o se redujo?
3. ¿Las métricas de performance mejoraron? (bundle size, carga, Lighthouse)
4. ¿Los patrones correctos se mantienen? (`m`, `dict` como prop, `SITE_CONFIG`, Zod factory)
5. ¿Hay nuevos hallazgos que cambien el roadmap?
6. ¿Las decisiones arquitecturales causan fricción operativa?

---

## Preguntas de Diseño Inicial (solo greenfield)

1. ¿Next.js es la elección correcta vs Astro/Nuxt/Remix/SvelteKit?
2. ¿Framer Motion justificado vs CSS puro/Tailwind?
3. ¿Sanity es el CMS correcto vs MDX/datos estáticos?
4. ¿Arquitectura i18n óptima? ¿Librería dedicada mejor?
5. ¿Debería deployarse como static export?
6. ¿Deuda técnica que pagar antes de seguir?

---

## Contexto del Proyecto

```
Tipo: Landing page + catálogo de productos (empresa colombiana de jugos naturales)
Audiencia: B2B (restaurantes, cafeterías) y consumidores finales
Contenido: Relativamente estático con datos de CMS
Idiomas: Español (principal) e Inglés
Estado: Desarrollo activo, aún no en producción
```

## Recursos

- **package.json** → Inventario completo de dependencias y versiones
- **LECCIONES_APRENDIDAS.md** → Errores anteriores y reglas del proyecto
- **node_modules/next/dist/docs/01-app/index.md** → Docs de Next.js instalada
- **app/** → Estructura de rutas y estrategias de rendering
- **components/** → Análisis de Server vs Client components
