import sys
sys.path.insert(0, ".")
from replicator.core.scraper_fitness import ScraperFitness

f = ScraperFitness()
data = f.compute()
print(f"FITNESS: {data['fitness']}/100")
print(f"  Exito busquedas:   {data['tasa_exito']}%")
print(f"  Fiab. tiendas:     {data['tasa_confianza_tiendas']}%")
print(f"  Sin errores:       {data['tasa_sin_errores']}%")
sys.exit(0 if data["fitness"] >= 50 else 1)
