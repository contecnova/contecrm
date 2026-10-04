import { Component, type ErrorInfo, type ReactNode } from "react";

import { Error as ErrorVisible } from "@/componentes/Estados";

/**
 * Una pantalla que revienta no puede llevarse la aplicación entera.
 *
 * **Medido el 04-10-2026**: no había ninguna frontera de error en todo el
 * front. Un `TypeError` al pintar cualquier pantalla —por ejemplo, una
 * respuesta de la API con una forma que esa pantalla no esperaba— dejaba el
 * `<body>` **vacío**. No una pantalla de error: vacío. Sin mensaje, sin menú,
 * sin forma de volver, y sin nada que el usuario pueda contarle a soporte.
 *
 * React desmonta el árbol entero cuando un error sube sin que nadie lo recoja,
 * y eso es exactamente lo que pasaba. Se descubrió montando las pruebas de
 * pantalla: la primera dio «0 elementos visibles» y el cuerpo entero en blanco.
 *
 * Va **dentro del marco**, no fuera, y es deliberado: lo que se cae es el
 * contenido de la pantalla, así que el menú, la barra y la paleta siguen ahí y
 * el usuario puede irse a otro sitio. Una frontera por encima del marco
 * convertiría el mismo fallo en la misma pantalla en blanco con otro texto.
 *
 * Y se **remonta al cambiar de ruta**: sin eso, una pantalla rota deja la
 * frontera abierta y la siguiente que se abra enseña el error de la anterior.
 */

type Props = { children: ReactNode; clave: string };
type Estado = { error: unknown };

export class Frontera extends Component<Props, Estado> {
  state: Estado = { error: null };

  static getDerivedStateFromError(error: unknown): Estado {
    return { error };
  }

  componentDidUpdate(anterior: Props): void {
    // Al cambiar de ruta se olvida el error: lo contrario deja al usuario
    // atrapado en la pantalla rota aunque navegue a otra.
    if (anterior.clave !== this.props.clave && this.state.error) {
      this.setState({ error: null });
    }
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    // A la consola del navegador, con el componente que lo provocó. No se manda
    // a ningún sitio desde aquí: el front no tiene canal propio de telemetría y
    // montarlo a escondidas en una frontera de error sería meter una llamada de
    // red en el peor momento posible.
    console.error("pantalla.error", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <ErrorVisible
          error={this.state.error}
          reintentar={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}
