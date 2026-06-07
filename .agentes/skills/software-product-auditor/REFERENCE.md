# software-product-auditor — Material de Referencia

> Checklists detallados por paso, formatos de hallazgo, escalas.
> Consultar bajo demanda durante la auditoría.

---

## Metodología Detallada

### PASO 1 — Identidad Visual y Diferenciación de Marca

**1A — Hero y first fold:**
- ¿Comunica propuesta de valor en ≤5 segundos?
- ¿El título es específico del negocio o aplicable a cualquier empresa?
- ¿Hay gradientes azul/morado, negro/neón u otros "sellos de IA" sin justificación?
- ¿El hero oculta información útil detrás de puro impacto visual?

**1B — Paleta de color:**
- ¿Colores con justificación de marca o defaults del framework?
- ¿Coherencia cromática entre todas las secciones?
- ¿Gradientes intencionales o decorativos sin razón?

**1C — Tipografía:**
- ¿Sistema tipográfico claro (max 2 familias) o mezcla inconsistente?
- ¿Jerarquía de tamaños y pesos o son arbitrarios?
- ¿"Serif instrument style", mayúsculas forzadas o fuentes de template IA?

**1D — Cards y componentes visuales:**
- ¿Cards con jerarquía real o todas idénticas con bordes redondeados y sombra?
- ¿Bento boxes con lógica de contenido o decorativos?
- ¿Iconografía usa emojis genéricos o iconos funcionales?

**1E — Consistencia global:**
- ¿Botones, espaciados, títulos, navegación mantienen sistema coherente?
- ¿El diseño guía al usuario o solo impresiona?
- ¿La página se ve única o intercambiable con cualquier competidor?

### PASO 2 — UX, Flujo de Navegación y Conversión

**2A — Propósito y CTA principal:**
- ¿Claro en primeros 5 segundos qué ofrece y qué hacer?
- ¿CTA principal visible, repetido estratégicamente?
- ¿Texto específico ("Solicitar cotización") vs genérico ("Saber más")?

**2B — Menú y navegación:**
- ¿Menú simple (≤7 opciones)?
- ¿Etiquetas claras y no ambiguas?
- ¿Rutas duplicadas o categorías unificables?

**2C — User journey mapping:**
```
Entrada → Sección informa → Sección genera confianza → Acción principal
```
Identificar dónde se rompe el flujo.

**2D — Formularios:**
- ¿Campos mínimos necesarios?
- ¿Labels visibles (no solo placeholders)?
- ¿Mensajes de error específicos y útiles?
- ¿Validación inline o solo al enviar?
- ¿Indicación de progreso en formularios multi-paso?

**2E — Patrones anti-UX de IA:**
- Formularios innecesariamente largos
- CTAs duplicados sin jerarquía
- Navegación con demasiados niveles
- Secciones sin función en el journey

### PASO 3 — Contenido, Propuesta de Valor y Tono

**3A — Propuesta de valor:**
- ¿Explica QUÉ problema resuelve, PARA QUIÉN y POR QUÉ es diferente?
- ¿Específica del negocio o serviría para cualquier competidor?
- ¿Frases tipo "solución innovadora", "experiencia única", "potencia tu negocio"?

**3B — Calidad y especificidad:**
Clasificar cada bloque como: Mantener | Mejorar | Reescribir | Eliminar

**3C — Tono:**
- ¿Humano, profesional y confiable o artificial y excesivamente positivo?
- ¿"Felicidad falsa" (optimismo sin sustento)?
- ¿Tono consistente en todo el sitio?

**3D — Veracidad:**
- ¿Afirmaciones, cifras, estudios verificables?
- ¿Precios, tamaños, ingredientes correctos?
- ¿Fechas (copyright, eventos, promociones) actualizadas?

**3E — Repetición:**
- ¿Secciones diciendo lo mismo con palabras diferentes?
- ¿Cada sección responde a una duda real?
- ¿Contenido optimizado para ayudar a decidir?

### PASO 4 — Responsive Design y Experiencia Móvil

**4A — Hero en móvil:**
- ¿Ocupa demasiado espacio antes de información útil?
- ¿Título y CTA legibles sin zoom?
- ¿Imágenes no se cortan ni deforman?

**4B — Menú móvil:**
- ¿Hamburguesa claro, funcional, fácil de cerrar?
- ¿Targets táctiles ≥44x44px?
- ¿Menú no cubre contenido importante?

**4C — Cards y grids:**
- ¿Cards no quedan angostas para ser legibles?
- ¿Textos no se truncan ni desbordan?
- ¿Scroll horizontal accidental?

**4D — Formularios en móvil:**
- ¿Inputs con type correcto (tel, email, number)?
- ¿Botones ≥44px?
- ¿Completable sin zoom?

**4E — Touch targets:**
- ¿Botones, enlaces ≥44x44px?
- ¿Espacio suficiente entre elementos táctiles?
- ¿Hover states con equivalente táctil (active/focus)?

**4F — Contenido oculto:**
- ¿Funcionalidades que desaparecen en móvil sin alternativa?
- ¿Imágenes responsivas con sizes correctos?

### PASO 5 — Microinteracciones y Animaciones

**5A — Propósito:**
Cada animación debe cumplir AL MENOS UNA de:
- Confirmar acción (feedback visual)
- Guiar atención del usuario
- Mostrar cambio de estado
- Mejorar comprensión de transición
- Reducir incertidumbre (carga, progreso)

**5B — Patrones problemáticos:**
- Scroll-jacking
- Efectos de cursor (luces, partículas que siguen al mouse)
- Fade-ins automáticos sin relación con scroll
- Hover excesivo en cada card
- Movimiento continuo sin propósito informativo

**5C — Performance:**
- ¿Propiedades aceleradas por GPU (transform, opacity)?
- ¿Animaciones que podrían ser CSS nativo en vez de JS?

**5D — Accesibilidad de movimiento:**
- ¿Respeta `prefers-reduced-motion`?
- ¿Mecanismo para pausar/desactivar animaciones?
- ¿Carruseles automáticos pausan con IntersectionObserver?

### PASO 6 — Credibilidad, Confianza y Transparencia

**6A — Quién está detrás:**
- ¿Muestra la empresa/persona responsable?
- ¿Página "Nosotros" con información real?
- ¿Fotos reales o generadas por IA?

**6B — Contacto verificable:**
- ¿Información completa (teléfono, email, dirección)?
- ¿Datos de SITE_CONFIG (no hardcodeados)?
- ¿Formulario funcional con confirmación visible?

**6C — Pruebas sociales:**
- ¿Testimonios auténticos (nombres, negocios, ubicaciones)?
- ¿Casos de uso, logos de clientes?
- ¿Cifras verificables?

**6D — Señales de legalidad:**
- ¿NIT/RUC visible donde corresponde?
- ¿Copyright actualizado?
- ¿Políticas adaptadas al proyecto real?

**6E — Autenticidad:**
- ¿Imágenes generadas por IA sin contexto?
- ¿Promesas realistas o exageradas?
- ¿Evita "fachada de startup"?

### PASO 7 — Privacidad Legal, Consentimiento y Ética

**7A — Cookies:**
- ¿Banner de cookie consent visible?
- ¿Consentimiento previo a tracking?
- ¿Clasificación por tipo (necesarias, analíticas, marketing)?
- ¿Rechazo posible sin perder funcionalidad?

**7B — Política de privacidad:**
- ¿Existe y está adaptada al proyecto real?
- ¿Explica qué datos, para qué, con quién, por cuánto tiempo?
- ¿Incluye derechos ARCO o equivalentes?

**7C — Términos y condiciones:**
- ¿Cubren uso del sitio, responsabilidades, propiedad intelectual?
- ¿Actualizados con legislación colombiana?

**7D — Transparencia IA:**
- ¿Contenido generado por IA declarado como tal?
- ¿Riesgo de que usuario crea que interactúa con humano?

**7E — Sesgos:**
- ¿Imágenes reflejan diversidad realista?
- ¿Sesgos perceptibles (género, raza, clase)?

---

## Formato de Hallazgo

```
[SEVERIDAD] ID-PROD — Componente/Sección
Síntoma: qué ve o experimenta el usuario
Impacto: cómo afecta conversión, confianza o percepción de marca
Recomendación: cambio concreto y accionable
```

**Tipos:** VIS | UX | CONT | RSP | MIC | CRE | LEG

## Hallazgo Referido (a otras skills)

```
[REFERIDO] [SEVERIDAD] → software-[code|architecture]-auditor
Área: descripción breve
Motivo: por qué no se profundiza aquí
```

## Escala de Severidad

| Nivel | Código | Descripción |
|-------|--------|-------------|
| Crítico | 🔴 CRIT | Impide conversión, genera desconfianza inmediata o incumplimiento legal |
| Alto | 🟠 HIGH | Impacto significativo en experiencia, marca o conversión |
| Medio | 🟡 MED | Subóptimo pero no bloqueante |
| Bajo | 🟢 LOW | Mejora incremental sin urgencia |
| Info | ℹ️ INFO | Observación estratégica |

## Recursos

- **LECCIONES_APRENDIDAS.md** → Causas raíz de errores (sección UX/producto)
- **messages/es.json** y **messages/en.json** → Tono, consistencia, contenido i18n
- **components/** → Componentes visuales sujetos a auditoría
- **public/imgs/** → Imágenes del sitio (credibilidad, autenticidad)
- **lib/config.ts** → Datos de contacto (verificar contra lo visible)
- **data/** → Datos estáticos del catálogo (verificar contra claims)
