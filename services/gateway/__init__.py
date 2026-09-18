"""Gateway: la única puerta de entrada.

Hace cuatro cosas y ninguna es de negocio:

  1. **Resuelve el tenant** (subdominio, cabecera, token o clave de API) y
     comprueba que puede operar.
  2. **Autentica** al que llama y resuelve sus permisos una vez, en vez de que
     lo haga cada servicio.
  3. **Aplica los límites** —rate limiting, cuotas, listas de IP— antes de que
     la petición cueste nada.
  4. **Enruta** al servicio que toca y propaga la identidad firmada.

Lo que **no** hace: lógica. Un gateway que valida reglas de negocio se convierte
en un monolito con otro nombre, y además en el punto donde toda la lógica es
imposible de probar aisladamente.

El resto de servicios no se llaman entre sí por HTTP salvo excepción declarada:
lo normal entre ellos es el bus, que no crea acoplamiento temporal. Si el
servicio de ventas tuviera que llamar al de identidad en cada petición, una
caída de identidad sería una caída de ventas.
"""
