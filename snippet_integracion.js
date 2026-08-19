/*
  Fragmento para integrar en tu web existente (donde ya cargas el JSON).
  Solo necesitas la parte de cálculo; el renderizado lo adaptas a tu
  librería de gráficas actual (Chart.js, D3, etc.).
*/

function contarDiasExtremos(rows) {
  const byYear = {};

  rows.forEach(r => {
    const year = Number(r.fecha.slice(0, 4));
    if (!byYear[year]) byYear[year] = { diasCalor: 0, nochesTropicales: 0 };

    const tmax = r.tmax === null || r.tmax === undefined ? null : Number(r.tmax);
    const tmin = r.tmin === null || r.tmin === undefined ? null : Number(r.tmin);

    if (tmax !== null && tmax >= 35) byYear[year].diasCalor++;
    if (tmin !== null && tmin >= 20) byYear[year].nochesTropicales++;
  });

  const years = Object.keys(byYear).map(Number).sort((a, b) => a - b);

  return {
    years,
    diasCalor: years.map(y => byYear[y].diasCalor),
    nochesTropicales: years.map(y => byYear[y].nochesTropicales)
  };
}

// Uso:
// const { years, diasCalor, nochesTropicales } = contarDiasExtremos(datosJson);
// -> pasa `years` como labels y `diasCalor` / `nochesTropicales` como datasets
//    a tu gráfica de barras existente (misma lógica que usas en "Tendencia anual").
