from index import handler

event = {
  "tenant_id": "asap",
  "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009",
  "query": "¿Segun los lineamientos de arquitectura, ¿Cual es la estrategia a seguir en cuanto a DDD y cual seria la forma mas optima de aplicarlo?"
}

event2 = {
  "tenant_id": "asap",
  "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009",
  "query": "Explicame en simples pasos como implementar una arquitectura hexagonal para crear los starters de microservicios en las distintas tecnologias segun los lineamientos definidos"
}

event3 = {
  "tenant_id": "asap",
  "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009",
  "query": "Explicame los beneficios de la arquitectura distribuida segun los lineamientos definidos"
}


event4 = {
  "tenant_id": "asap",
  "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009",
  "query": "definime los pasos del ciclo de vida de desarrollo segun los lineamientos definidos"
}

event8 = {
  "tenant_id": "asap",
  "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009",
  "query": "como garantizo una integracion segura con al agente de gitlab?"
}

event9 = {
  "tenant_id": "asap",
  "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009",
  "query": "como es el flujo del pipeline ci/cd y como se configura?"
}

event10 = {
  "tenant_id": "asap",
  "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009",
  "query": "haceme un resumen de todos los aspectos relevantes de kubernetes"
}

event5 = {
  "tenant_id": "educacion",
  "agent_id": "08cb9a19-7b8c-4b63-b4f2-7ccb3de1067c",
  "query": "Haceme un listado separado por año de los Aspectos lingüísticos en lenguas adicionales"
}


event6 = {
  "tenant_id": "educacion",
  "agent_id": "08cb9a19-7b8c-4b63-b4f2-7ccb3de1067c",
  "query": "Segun el contexto y la experiencia decime como deberian ser evaliadops los modelos linguisticos de lenguas adicionales?"
}

event7 = {
  "tenant_id": "educacion",
  "agent_id": "08cb9a19-7b8c-4b63-b4f2-7ccb3de1067c",
  "query": "Segun el contexto y la experiencia decime cuales serian los objetivos de aprendizaje segun el nivel en lenguas adicionales?"
}


event11 = {
  "tenant_id": "gp",
  "agent_id": "e825fa81-da9a-4b39-934e-a667148428aa",
  "query": "Segun el contexto decime con que tecnologias deberia encarar una aplicacion web desde cero"
}

event12 = {
  "tenant_id": "gp",
  "agent_id": "e825fa81-da9a-4b39-934e-a667148428aa",
  "query": "Que patrones de diseño estan sugeridos en los lineamientos"
}

event13 = {
  "tenant_id": "gp",
  "agent_id": "e825fa81-da9a-4b39-934e-a667148428aa",
  "query": "que lenguajes de programacion puedo disponer para el backend?"
}


event14 = {
  "tenant_id": "gp",
  "agent_id": "e825fa81-da9a-4b39-934e-a667148428aa",
  "query": "que lenguajes de programacion puedo disponer para el backend?"
}


event14 = {
  "tenant_id": "gp",
  "agent_id": "e825fa81-da9a-4b39-934e-a667148428aa",
  "query": "que lenguajes de programacion puedo disponer para el backend?"
}

event15 = {
  "tenant_id": "gp",
  "agent_id": "e825fa81-da9a-4b39-934e-a667148428aa",
  "query": "de todas las tecnologias sobre todo On Prem , listame aquellas que creas que pueden llegar a tener un costo de licenciamiento alto"
}


event16 = {
  "tenant_id": "gp",
  "agent_id": "e825fa81-da9a-4b39-934e-a667148428aa",
  "query": "Listame los api managers y sus posibles modelos de pricing"
}

handler(event16,None)