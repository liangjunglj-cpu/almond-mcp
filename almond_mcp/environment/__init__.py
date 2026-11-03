"""Environmental analysis: climate (EPW), sun and sky, daylight, solar radiation, thermal comfort and zone
energy - a clean-room implementation of published methods, with no third-party simulation engine.

Modules, bottom up:

  epw        EnergyPlus weather files: parse, validate, repair, summarise
  solar      sun position (NOAA / Meeus), sun path, solar time
  sky        Tregenza / Reinhart sky patches, Perez luminous efficacy and all-weather sky, CIE skies,
             hourly sky matrices
  scene      triangle scenes, materials (opaque, glazing, shades), sensor grids, shoebox rooms
  raytrace   vectorised BVH ray casting (numpy)
  daylight   daylight coefficients by backward path tracing; DF, point-in-time and annual metrics
             (sDA / ASE per IES LM-83, UDI, DA, cDA), simplified DGP
  radiation  cumulative and annual irradiance on surfaces
  comfort    psychrometrics, PMV/PPD (ISO 7730), adaptive comfort (ASHRAE 55, EN 16798-1), CIBSE TM52
  climate    climate summaries: monthly statistics, degree days, comfort and strategy hours, wind rose
  thermal    hourly zone model, ISO 13790 5R1C, with ray-traced solar gains
  render     false-colour plan images (Pillow)
  rhino      C# scripts that export scene meshes from Rhino and draw result meshes back

Every function works in SI units and metres. Nothing here talks to Rhino directly.
"""
