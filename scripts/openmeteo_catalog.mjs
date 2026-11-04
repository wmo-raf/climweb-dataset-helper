#!/usr/bin/env node
/**
 * Regenerates the Open-Meteo datasets of dataset_helper/static/dataset_helper/catalog.json.
 *
 * Usage (Node >= 18):
 *
 *   npm install --no-save @openmeteo/weather-map-layer@0.3.0
 *   node scripts/openmeteo_catalog.mjs [--dry-run] [--regional] [--version 2026.10.22]
 *
 * or point it at a copy of the package installed elsewhere (e.g. the map viewer's):
 *
 *   node scripts/openmeteo_catalog.mjs --package ../geomapviewer/node_modules/@openmeteo/weather-map-layer
 *
 * The package decides what the map viewer can render, so it is the source of the
 * weather models (domains), of the variables each one can show (stored in its
 * latest run or derived from them, e.g. wind speed from its u/v components), of
 * their labels and of their footprints.
 *
 * What gets in:
 *   - every concrete domain whose latest.json is published right now (seamless
 *     composites have no folder of their own on the server) and covers the
 *     whole globe: regional models are left out unless --regional is passed;
 *   - the variables of VARIABLES below available in that run: the ones the
 *     package has a colour scale for (it renders the others, e.g. the CAMS air
 *     quality species, with the temperature scale), at standard pressure levels
 *     and heights, leaving out u/v components and directions that duplicate a
 *     speed or a height.
 *
 * Each variable of each domain is one dataset, filed under its thematic category
 * in an "Open-Meteo forecast" subcategory (the sub-seasonal EC46 run under
 * "Climate"). They are disabled by default: admins pick the ones they want in
 * the helper. With --regional, regional models carry their footprint as
 * `coverage`, so the helper only loads them when they cover the configured
 * country.
 *
 * Datasets made only of openmeteo layers belong to this script: each run drops
 * them before adding the new ones, so the rest of the catalog can still be
 * edited by hand.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const CATALOG_PATH = path.resolve(
	path.dirname(fileURLToPath(import.meta.url)),
	'../dataset_helper/static/dataset_helper/catalog.json'
);
// default of geomanager's OpenMeteoLayer.base_url, so the catalog leaves it out
const BASE_URL = 'https://openmeteo.s3.amazonaws.com/data_spatial';
const PRESSURE_LEVELS = [850, 700, 500, 200];
const WIND_HEIGHTS = [10, 80, 100, 120];
// the map viewer refreshes the run list this often (minutes)
const AUTO_UPDATE_INTERVAL = 60;
// footprint simplification tolerance, in degrees
const COVERAGE_TOLERANCE = 0.2;

// ── Command line ─────────────────────────────────────────────────────────────

const args = process.argv.slice(2);
const option = (name) => {
	const i = args.indexOf(name);
	return i === -1 ? undefined : args[i + 1];
};
const dryRun = args.includes('--dry-run');
const includeRegional = args.includes('--regional');

const loadPackage = async () => {
	const location = option('--package');
	if (!location) return import('@openmeteo/weather-map-layer');
	const entry = location.endsWith('.mjs') ? location : path.join(location, 'dist/index.mjs');
	return import(pathToFileURL(path.resolve(entry)).href);
};

const om = await loadPackage();

// ── Translations ─────────────────────────────────────────────────────────────

const t = (en, fr, es, pt, ar) => ({ en, fr, es, pt, ar });
const LANGS = ['en', 'fr', 'es', 'pt', 'ar'];
const mapLangs = (fn) => Object.fromEntries(LANGS.map((lang) => [lang, fn(lang)]));

const SUBCATEGORY = t(
	'Open-Meteo forecast',
	'Prévisions Open-Meteo',
	'Pronóstico Open-Meteo',
	'Previsão Open-Meteo',
	'توقعات Open-Meteo'
);
const SUBSEASONAL_SUBCATEGORY = t(
	'Open-Meteo sub-seasonal forecast',
	'Prévisions sous-saisonnières Open-Meteo',
	'Pronóstico subestacional Open-Meteo',
	'Previsão subsazonal Open-Meteo',
	'توقعات Open-Meteo دون الموسمية'
);
const GENERATED_SUBCATEGORIES = [SUBCATEGORY.en, SUBSEASONAL_SUBCATEGORY.en];

// key -> English title of the catalog category the datasets go to
const CATEGORIES = {
	temperature: 'Temperature',
	precipitation: 'Precipitation',
	wind: 'Wind',
	atmosphere: 'Atmosphere',
	ocean: 'Ocean',
	drought: 'Drought',
	climate: 'Climate'
};

const GLOBAL = t('Global', 'Mondial', 'Global', 'Global', 'عالمي');

const REGIONS = {
	austria: t('Austria and the Alps', 'Autriche et Alpes', 'Austria y los Alpes', 'Áustria e Alpes', 'النمسا وجبال الألب'),
	canada: t('Canada', 'Canada', 'Canadá', 'Canadá', 'كندا'),
	central_europe: t('Central Europe', 'Europe centrale', 'Europa central', 'Europa Central', 'أوروبا الوسطى'),
	conus: t(
		'Contiguous United States',
		'États-Unis contigus',
		'Estados Unidos contiguos',
		'Estados Unidos contíguos',
		'الولايات المتحدة المتجاورة'
	),
	czechia: t('Czechia', 'Tchéquie', 'Chequia', 'Chéquia', 'التشيك'),
	europe: t('Europe', 'Europe', 'Europa', 'Europa', 'أوروبا'),
	france: t(
		'France and neighbouring countries',
		'France et pays voisins',
		'Francia y países vecinos',
		'França e países vizinhos',
		'فرنسا والبلدان المجاورة'
	),
	germany: t(
		'Germany and neighbouring countries',
		'Allemagne et pays voisins',
		'Alemania y países vecinos',
		'Alemanha e países vizinhos',
		'ألمانيا والبلدان المجاورة'
	),
	italy: t('Italy', 'Italie', 'Italia', 'Itália', 'إيطاليا'),
	japan: t('Japan', 'Japon', 'Japón', 'Japão', 'اليابان'),
	netherlands: t('Netherlands', 'Pays-Bas', 'Países Bajos', 'Países Baixos', 'هولندا'),
	nordic: t('Nordic countries', 'Pays nordiques', 'Países nórdicos', 'Países nórdicos', 'بلدان الشمال الأوروبي'),
	north_america: t('North America', 'Amérique du Nord', 'América del Norte', 'América do Norte', 'أمريكا الشمالية'),
	ocean_band: t(
		'Oceans between 15°S and 52.5°N',
		'Océans entre 15°S et 52,5°N',
		'Océanos entre 15°S y 52,5°N',
		'Oceanos entre 15°S e 52,5°N',
		'المحيطات بين 15° جنوبًا و52.5° شمالًا'
	),
	switzerland: t('Switzerland and the Alps', 'Suisse et Alpes', 'Suiza y los Alpes', 'Suíça e Alpes', 'سويسرا وجبال الألب'),
	uk: t(
		'United Kingdom and Ireland',
		'Royaume-Uni et Irlande',
		'Reino Unido e Irlanda',
		'Reino Unido e Irlanda',
		'المملكة المتحدة وأيرلندا'
	),
	western_canada: t('Western Canada', 'Ouest du Canada', 'Oeste de Canadá', 'Oeste do Canadá', 'غرب كندا')
};

// first matching prefix wins
const DOMAIN_REGIONS = [
	['cams_europe', 'europe'],
	['chmi_aladin_central_europe', 'central_europe'],
	['chmi_aladin_cz', 'czechia'],
	['dmi_harmonie_arome_europe', 'europe'],
	['dwd_icon_eu', 'europe'],
	['dwd_icon_d2', 'germany'],
	['dwd_ewam', 'europe'],
	['ncep_hrrr_conus', 'conus'],
	['ncep_nbm_conus', 'conus'],
	['ncep_nam_conus', 'conus'],
	['ncep_gfswave016', 'ocean_band'],
	['cmc_gem_hrdps_west', 'western_canada'],
	['cmc_gem_hrdps', 'canada'],
	['cmc_gem_rdps', 'north_america'],
	['geosphere_arome_austria', 'austria'],
	['italia_meteo_arpae', 'italy'],
	['jma_msm', 'japan'],
	['meteofrance_arpege_europe', 'europe'],
	['meteofrance_arome', 'france'],
	['metno_nordic', 'nordic'],
	['knmi_harmonie_arome_europe', 'europe'],
	['knmi_harmonie_arome_netherlands', 'netherlands'],
	['meteoswiss_', 'switzerland'],
	['ukmo_uk_', 'uk']
];

const PROVIDERS = [
	['cams_', 'ECMWF / CAMS'],
	['chmi_', 'CHMI'],
	['cma_', 'CMA'],
	['dmi_', 'DMI'],
	['dwd_', 'DWD'],
	['ncep_', 'NOAA NCEP'],
	['ecmwf_', 'ECMWF'],
	['cmc_gem_', 'ECCC'],
	['geosphere_', 'GeoSphere Austria'],
	['italia_meteo_', 'ItaliaMeteo-ARPAE'],
	['jma_', 'JMA'],
	['meteofrance_', 'Météo-France'],
	['metno_', 'MET Norway'],
	['kma_', 'KMA'],
	['knmi_', 'KNMI'],
	['meteoswiss_', 'MeteoSwiss'],
	['ukmo_', 'UK Met Office']
];

const DOCS = 'https://open-meteo.com/en/docs';
const MARINE_DOMAINS = /^(ecmwf_wam|ncep_gfswave|dwd_[ge]wam|meteofrance_(wave|currents|sea_surface_temperature))/;
const ENSEMBLE_DOMAINS = /(ensemble|_eps|gefs|geps)/;
const PROVIDER_DOCS = [
	['cams_', 'air-quality-api'],
	['chmi_', 'chmi-api'],
	['cma_', 'cma-api'],
	['dmi_', 'dmi-api'],
	['dwd_', 'dwd-api'],
	['ncep_', 'gfs-api'],
	['ecmwf_', 'ecmwf-api'],
	['cmc_gem_', 'gem-api'],
	['geosphere_', 'geosphere-austria-api'],
	['italia_meteo_', 'italia-meteo-arpae-api'],
	['jma_', 'jma-api'],
	['meteofrance_', 'meteofrance-api'],
	['metno_', 'metno-api'],
	['kma_', 'kma-api'],
	['knmi_', 'knmi-api'],
	['meteoswiss_', 'meteoswiss-api'],
	['ukmo_', 'ukmo-api']
];

// clearer model names than the package's short labels
const LABELS = {
	cmc_gem_gdps_15km_upper_level: 'GEM Global (upper levels)',
	geosphere_arome_austria: 'GeoSphere AROME Austria',
	italia_meteo_arpae_icon_2i: 'ItaliaMeteo ARPAE ICON-2I',
	jma_msm_upper_level: 'JMA MSM (upper levels)',
	ncep_aigfs025: 'NOAA AIGFS 0.25°',
	ncep_gefs025: 'NOAA GEFS 0.25°',
	ncep_gefs05: 'NOAA GEFS 0.5°',
	ncep_gfs013: 'NOAA GFS 0.13°',
	ncep_gfs025: 'NOAA GFS 0.25°',
	ncep_gfs_graphcast025: 'NOAA GraphCast GFS 0.25°',
	ncep_gfswave016: 'NOAA GFS Wave 0.16°',
	ncep_gfswave025: 'NOAA GFS Wave 0.25°',
	ncep_hgefs025_ensemble_mean: 'NOAA HGEFS 0.25° Ensemble Mean',
	ncep_hrrr_conus: 'NOAA HRRR CONUS',
	ncep_hrrr_conus_15min: 'NOAA HRRR CONUS 15 min',
	ncep_nam_conus: 'NOAA NAM CONUS',
	ncep_nbm_conus: 'NOAA NBM CONUS',
	ukmo_global_deterministic_10km: 'UK Met Office Global 10 km',
	ukmo_global_ensemble_20km: 'UK Met Office MOGREPS-G 20 km',
	ukmo_uk_deterministic_2km: 'UK Met Office UKV 2 km',
	ukmo_uk_ensemble_2km: 'UK Met Office MOGREPS-UK 2 km'
};

// grids the package gives no spacing for, or a non-obvious one
const RESOLUTIONS = {
	cmc_gem_hrdps: '2.5 km',
	ecmwf_ec46_ensemble_mean: '36 km',
	ecmwf_ec46_weekly: '36 km',
	ecmwf_ifs: '9 km',
	ecmwf_seas5_monthly: '36 km',
	ecmwf_wam: '9 km',
	knmi_harmonie_arome_europe: '5.5 km',
	metno_nordic_pp: '1 km',
	ncep_hrrr_conus: '3 km',
	ncep_hrrr_conus_15min: '3 km',
	ncep_nam_conus: '3 km'
};

const EVERY = {
	'15_minute': t('every 15 minutes', 'toutes les 15 minutes', 'cada 15 minutos', 'a cada 15 minutos', 'كل 15 دقيقة'),
	hourly: t('every hour', 'toutes les heures', 'cada hora', 'a cada hora', 'كل ساعة'),
	'3_hourly': t('every 3 hours', 'toutes les 3 heures', 'cada 3 horas', 'a cada 3 horas', 'كل 3 ساعات'),
	'6_hourly': t('every 6 hours', 'toutes les 6 heures', 'cada 6 horas', 'a cada 6 horas', 'كل 6 ساعات'),
	'12_hourly': t('every 12 hours', 'toutes les 12 heures', 'cada 12 horas', 'a cada 12 horas', 'كل 12 ساعة'),
	daily: t('every day', 'chaque jour', 'cada día', 'todos os dias', 'كل يوم'),
	weekly_on_monday: t('every week', 'chaque semaine', 'cada semana', 'todas as semanas', 'كل أسبوع'),
	monthly: t('every month', 'chaque mois', 'cada mes', 'todos os meses', 'كل شهر')
};
const FREQUENCIES = {
	hourly: t('Hourly', 'Toutes les heures', 'Cada hora', 'A cada hora', 'كل ساعة'),
	'3_hourly': t('Every 3 hours', 'Toutes les 3 heures', 'Cada 3 horas', 'A cada 3 horas', 'كل 3 ساعات'),
	'6_hourly': t('Every 6 hours', 'Toutes les 6 heures', 'Cada 6 horas', 'A cada 6 horas', 'كل 6 ساعات'),
	'12_hourly': t('Every 12 hours', 'Toutes les 12 heures', 'Cada 12 horas', 'A cada 12 horas', 'كل 12 ساعة'),
	daily: t('Daily', 'Quotidienne', 'Diaria', 'Diária', 'يومي'),
	monthly: t('Monthly', 'Mensuelle', 'Mensual', 'Mensal', 'شهري')
};

const FUNCTIONS = {
	weather: t(
		'Numerical weather prediction',
		'Prévision numérique du temps',
		'Predicción numérica del tiempo',
		'Previsão numérica do tempo',
		'التنبؤ العددي بالطقس'
	),
	marine: t(
		'Numerical ocean forecast',
		'Prévision océanique numérique',
		'Pronóstico oceánico numérico',
		'Previsão oceânica numérica',
		'التنبؤ العددي بحالة المحيطات'
	),
	composition: t(
		'Atmospheric composition forecast',
		'Prévision de la composition atmosphérique',
		'Pronóstico de la composición atmosférica',
		'Previsão da composição atmosférica',
		'التنبؤ بتركيب الغلاف الجوي'
	),
	subseasonal: t(
		'Sub-seasonal forecast',
		'Prévision sous-saisonnière',
		'Pronóstico subestacional',
		'Previsão subsazonal',
		'التنبؤ دون الموسمي'
	)
};

const overview = (variable, model, provider, every) =>
	t(
		`“${variable.en}” forecast by the ${model} model (${provider}), distributed by Open-Meteo. ` +
			`The map shows the latest available model run; new runs are published ${every.en}.`,
		`Prévision « ${variable.fr} » du modèle ${model} (${provider}), diffusée par Open-Meteo. ` +
			`La carte affiche la dernière exécution disponible du modèle ; une nouvelle exécution est publiée ${every.fr}.`,
		`Pronóstico «${variable.es}» del modelo ${model} (${provider}), distribuido por Open-Meteo. ` +
			`El mapa muestra la última ejecución disponible del modelo; se publica una nueva ejecución ${every.es}.`,
		`Previsão «${variable.pt}» do modelo ${model} (${provider}), distribuída pelo Open-Meteo. ` +
			`O mapa mostra a última execução disponível do modelo; uma nova execução é publicada ${every.pt}.`,
		`توقعات «${variable.ar}» من النموذج ${model} (${provider})، يوزعها Open-Meteo. ` +
			`تعرض الخريطة أحدث تشغيل متاح للنموذج؛ ويُنشر تشغيل جديد ${every.ar}.`
	);

// ── Variables ────────────────────────────────────────────────────────────────

const VARIABLE_NAMES = om.variableOptions.map((v) => v.value);

const one = (category, name, title) => [{ category, name, title }];
const perLevel = (category, levels, name, title) =>
	levels.map((level) => ({ category, name: name(level), title: title(level) }));
// soil layers differ per model: take the package's names, shallowest first
const soilLayers = (category, prefix, title) =>
	VARIABLE_NAMES.map((name) => [name, name.match(new RegExp(`^${prefix}_(\\d+)(?:_to_(\\d+))?cm$`))])
		.filter(([, m]) => m)
		.sort(([, a], [, b]) => a[1] - b[1] || (a[2] || 0) - (b[2] || 0))
		.map(([name, [, top, bottom]]) => {
			const depth = bottom ? `${top}–${bottom}` : top;
			return { category, name, title: title(`${depth} cm`, `${depth} سم`) };
		});

const VARIABLES = [
	// Temperature
	...one('temperature', 'temperature_2m', t('2-metre temperature', 'Température à 2 m', 'Temperatura a 2 m', 'Temperatura a 2 m', 'درجة الحرارة على ارتفاع 2 م')),
	...one('temperature', 'temperature_2m_max', t('2-metre maximum temperature', 'Température maximale à 2 m', 'Temperatura máxima a 2 m', 'Temperatura máxima a 2 m', 'درجة الحرارة العظمى على ارتفاع 2 م')),
	...one('temperature', 'temperature_2m_min', t('2-metre minimum temperature', 'Température minimale à 2 m', 'Temperatura mínima a 2 m', 'Temperatura mínima a 2 m', 'درجة الحرارة الصغرى على ارتفاع 2 م')),
	...one('temperature', 'apparent_temperature', t('Apparent temperature', 'Température ressentie', 'Temperatura aparente', 'Temperatura aparente', 'درجة الحرارة المحسوسة')),
	...one('temperature', 'dew_point_2m', t('2-metre dew point temperature', 'Point de rosée à 2 m', 'Punto de rocío a 2 m', 'Ponto de orvalho a 2 m', 'درجة حرارة نقطة الندى على ارتفاع 2 م')),
	...one('temperature', 'wet_bulb_temperature_2m', t('2-metre wet-bulb temperature', 'Température du thermomètre mouillé à 2 m', 'Temperatura de bulbo húmedo a 2 m', 'Temperatura de bulbo úmido a 2 m', 'درجة حرارة البصيلة الرطبة على ارتفاع 2 م')),
	...one('temperature', 'surface_temperature', t('Surface (skin) temperature', 'Température de surface', 'Temperatura de la superficie', 'Temperatura da superfície', 'درجة حرارة السطح')),
	...perLevel('temperature', PRESSURE_LEVELS, (l) => `temperature_${l}hPa`, (l) =>
		t(`${l} hPa temperature`, `Température à ${l} hPa`, `Temperatura a ${l} hPa`, `Temperatura a ${l} hPa`, `درجة الحرارة عند ${l} هكتوباسكال`)),
	...soilLayers('temperature', 'soil_temperature', (d, dAr) =>
		t(`Soil temperature (${d})`, `Température du sol (${d})`, `Temperatura del suelo (${d})`, `Temperatura do solo (${d})`, `درجة حرارة التربة (${dAr})`)),

	// Precipitation
	...one('precipitation', 'precipitation', t('Precipitation', 'Précipitations', 'Precipitación', 'Precipitação', 'الهطول')),
	...one('precipitation', 'rain', t('Rain', 'Pluie', 'Lluvia', 'Chuva', 'المطر')),
	...one('precipitation', 'showers', t('Showers (convective precipitation)', 'Averses (précipitations convectives)', 'Chubascos (precipitación convectiva)', 'Aguaceiros (precipitação convectiva)', 'الزخات (الهطول الحملي)')),
	...one('precipitation', 'precipitation_probability', t('Precipitation probability', 'Probabilité de précipitations', 'Probabilidad de precipitación', 'Probabilidade de precipitação', 'احتمال الهطول')),
	...one('precipitation', 'snowfall', t('Snowfall', 'Chutes de neige', 'Nevadas', 'Queda de neve', 'تساقط الثلوج')),
	...one('precipitation', 'snowfall_water_equivalent', t('Snowfall water equivalent', 'Équivalent en eau des chutes de neige', 'Equivalente en agua de la nevada', 'Equivalente em água da queda de neve', 'المكافئ المائي لتساقط الثلوج')),
	...one('precipitation', 'snow_depth', t('Snow depth', 'Épaisseur de neige', 'Espesor de nieve', 'Espessura de neve', 'عمق الثلج')),
	...one('precipitation', 'snow_depth_water_equivalent', t('Snow depth water equivalent', 'Équivalent en eau du manteau neigeux', 'Equivalente en agua de la nieve acumulada', 'Equivalente em água da neve acumulada', 'المكافئ المائي للغطاء الثلجي')),
	...one('precipitation', 'snowfall_height', t('Snowfall height (snow line)', 'Limite pluie-neige', 'Cota de nieve', 'Cota de neve', 'ارتفاع خط الثلج')),

	// Wind
	...perLevel('wind', WIND_HEIGHTS, (h) => `wind_speed_${h}m`, (h) =>
		t(`${h}-metre wind speed`, `Vitesse du vent à ${h} m`, `Velocidad del viento a ${h} m`, `Velocidade do vento a ${h} m`, `سرعة الرياح على ارتفاع ${h} م`)),
	...one('wind', 'wind_gusts_10m', t('10-metre wind gusts', 'Rafales de vent à 10 m', 'Rachas de viento a 10 m', 'Rajadas de vento a 10 m', 'هبات الرياح على ارتفاع 10 م')),
	...perLevel('wind', PRESSURE_LEVELS, (l) => `wind_speed_${l}hPa`, (l) =>
		t(`${l} hPa wind speed`, `Vitesse du vent à ${l} hPa`, `Velocidad del viento a ${l} hPa`, `Velocidade do vento a ${l} hPa`, `سرعة الرياح عند ${l} هكتوباسكال`)),

	// Atmosphere
	...one('atmosphere', 'pressure_msl', t('Mean sea level pressure', 'Pression au niveau de la mer', 'Presión al nivel del mar', 'Pressão ao nível do mar', 'الضغط عند مستوى سطح البحر')),
	...one('atmosphere', 'relative_humidity_2m', t('2-metre relative humidity', 'Humidité relative à 2 m', 'Humedad relativa a 2 m', 'Umidade relativa a 2 m', 'الرطوبة النسبية على ارتفاع 2 م')),
	...one('atmosphere', 'vapour_pressure_deficit', t('Vapour pressure deficit', 'Déficit de pression de vapeur', 'Déficit de presión de vapor', 'Déficit de pressão de vapor', 'عجز ضغط البخار')),
	...one('atmosphere', 'cloud_cover', t('Total cloud cover', 'Nébulosité totale', 'Nubosidad total', 'Nebulosidade total', 'الغطاء السحابي الكلي')),
	...one('atmosphere', 'cloud_cover_low', t('Low cloud cover', 'Nébulosité basse', 'Nubosidad baja', 'Nebulosidade baixa', 'الغطاء السحابي المنخفض')),
	...one('atmosphere', 'cloud_cover_mid', t('Medium cloud cover', 'Nébulosité moyenne', 'Nubosidad media', 'Nebulosidade média', 'الغطاء السحابي المتوسط')),
	...one('atmosphere', 'cloud_cover_high', t('High cloud cover', 'Nébulosité haute', 'Nubosidad alta', 'Nebulosidade alta', 'الغطاء السحابي العالي')),
	...one('atmosphere', 'cloud_base', t('Cloud base height', 'Hauteur de la base des nuages', 'Altura de la base de las nubes', 'Altura da base das nuvens', 'ارتفاع قاعدة السحب')),
	...one('atmosphere', 'cloud_top', t('Cloud top height', 'Hauteur du sommet des nuages', 'Altura de la cima de las nubes', 'Altura do topo das nuvens', 'ارتفاع قمة السحب')),
	...one('atmosphere', 'convective_cloud_base', t('Convective cloud base height', 'Hauteur de la base des nuages convectifs', 'Altura de la base de las nubes convectivas', 'Altura da base das nuvens convectivas', 'ارتفاع قاعدة السحب الحملية')),
	...one('atmosphere', 'convective_cloud_top', t('Convective cloud top height', 'Hauteur du sommet des nuages convectifs', 'Altura de la cima de las nubes convectivas', 'Altura do topo das nuvens convectivas', 'ارتفاع قمة السحب الحملية')),
	...one('atmosphere', 'cape', t('Convective available potential energy (CAPE)', 'Énergie potentielle de convection disponible (CAPE)', 'Energía potencial convectiva disponible (CAPE)', 'Energia potencial convectiva disponível (CAPE)', 'طاقة الحمل الكامنة المتاحة (CAPE)')),
	...one('atmosphere', 'convective_inhibition', t('Convective inhibition (CIN)', 'Inhibition convective (CIN)', 'Inhibición convectiva (CIN)', 'Inibição convectiva (CIN)', 'كبح الحمل الحراري (CIN)')),
	...one('atmosphere', 'visibility', t('Visibility', 'Visibilité', 'Visibilidad', 'Visibilidade', 'مدى الرؤية')),
	...one('atmosphere', 'freezing_level_height', t('Freezing level height', 'Altitude de l’isotherme 0 °C', 'Altura del nivel de congelación', 'Altura do nível de congelação', 'ارتفاع مستوى التجمد')),
	...one('atmosphere', 'boundary_layer_height', t('Boundary layer height', 'Hauteur de la couche limite', 'Altura de la capa límite', 'Altura da camada limite', 'ارتفاع الطبقة الحدية')),
	...one('atmosphere', 'total_column_integrated_water_vapour', t('Total column water vapour', 'Vapeur d’eau intégrée sur la colonne', 'Vapor de agua total en la columna', 'Vapor de água total na coluna', 'بخار الماء الكلي في العمود الجوي')),
	...one('atmosphere', 'shortwave_radiation', t('Shortwave solar radiation', 'Rayonnement solaire de courte longueur d’onde', 'Radiación solar de onda corta', 'Radiação solar de onda curta', 'الإشعاع الشمسي قصير الموجة')),
	...one('atmosphere', 'direct_radiation', t('Direct solar radiation', 'Rayonnement solaire direct', 'Radiación solar directa', 'Radiação solar direta', 'الإشعاع الشمسي المباشر')),
	...one('atmosphere', 'diffuse_radiation', t('Diffuse solar radiation', 'Rayonnement solaire diffus', 'Radiación solar difusa', 'Radiação solar difusa', 'الإشعاع الشمسي المنتشر')),
	...one('atmosphere', 'uv_index', t('UV index', 'Indice UV', 'Índice UV', 'Índice UV', 'مؤشر الأشعة فوق البنفسجية')),
	...one('atmosphere', 'uv_index_clear_sky', t('Clear-sky UV index', 'Indice UV par ciel clair', 'Índice UV con cielo despejado', 'Índice UV com céu limpo', 'مؤشر الأشعة فوق البنفسجية في سماء صافية')),
	...one('atmosphere', 'latent_heat_flux', t('Surface latent heat flux', 'Flux de chaleur latente en surface', 'Flujo de calor latente en superficie', 'Fluxo de calor latente à superfície', 'تدفق الحرارة الكامنة السطحي')),
	...one('atmosphere', 'sensible_heat_flux', t('Surface sensible heat flux', 'Flux de chaleur sensible en surface', 'Flujo de calor sensible en superficie', 'Fluxo de calor sensível à superfície', 'تدفق الحرارة المحسوسة السطحي')),
	...perLevel('atmosphere', PRESSURE_LEVELS, (l) => `relative_humidity_${l}hPa`, (l) =>
		t(`${l} hPa relative humidity`, `Humidité relative à ${l} hPa`, `Humedad relativa a ${l} hPa`, `Umidade relativa a ${l} hPa`, `الرطوبة النسبية عند ${l} هكتوباسكال`)),
	...perLevel('atmosphere', PRESSURE_LEVELS, (l) => `geopotential_height_${l}hPa`, (l) =>
		t(`${l} hPa geopotential height`, `Hauteur du géopotentiel à ${l} hPa`, `Altura geopotencial a ${l} hPa`, `Altura geopotencial a ${l} hPa`, `الارتفاع الجيوبوتنشيالي عند ${l} هكتوباسكال`)),
	...perLevel('atmosphere', PRESSURE_LEVELS, (l) => `vertical_velocity_${l}hPa`, (l) =>
		t(`${l} hPa vertical velocity`, `Vitesse verticale à ${l} hPa`, `Velocidad vertical a ${l} hPa`, `Velocidade vertical a ${l} hPa`, `السرعة الرأسية عند ${l} هكتوباسكال`)),

	// Ocean
	...one('ocean', 'wave_height', t('Significant wave height', 'Hauteur significative des vagues', 'Altura significativa de las olas', 'Altura significativa das ondas', 'الارتفاع الملحوظ للأمواج')),
	...one('ocean', 'wave_period', t('Mean wave period', 'Période moyenne des vagues', 'Período medio de las olas', 'Período médio das ondas', 'متوسط فترة الأمواج')),
	...one('ocean', 'wave_peak_period', t('Peak wave period', 'Période de pic des vagues', 'Período pico de las olas', 'Período de pico das ondas', 'فترة ذروة الأمواج')),
	...one('ocean', 'wind_wave_height', t('Wind wave height', 'Hauteur de la mer du vent', 'Altura del mar de viento', 'Altura das vagas', 'ارتفاع أمواج الرياح')),
	...one('ocean', 'swell_wave_height', t('Swell height', 'Hauteur de la houle', 'Altura del mar de fondo', 'Altura da ondulação', 'ارتفاع موج العباب')),
	...one('ocean', 'swell_wave_period', t('Swell period', 'Période de la houle', 'Período del mar de fondo', 'Período da ondulação', 'فترة موج العباب')),
	...one('ocean', 'secondary_swell_wave_height', t('Secondary swell height', 'Hauteur de la houle secondaire', 'Altura del mar de fondo secundario', 'Altura da ondulação secundária', 'ارتفاع موج العباب الثانوي')),
	...one('ocean', 'secondary_swell_wave_period', t('Secondary swell period', 'Période de la houle secondaire', 'Período del mar de fondo secundario', 'Período da ondulação secundária', 'فترة موج العباب الثانوي')),
	...one('ocean', 'tertiary_swell_wave_height', t('Tertiary swell height', 'Hauteur de la houle tertiaire', 'Altura del mar de fondo terciario', 'Altura da ondulação terciária', 'ارتفاع موج العباب الثالثي')),
	...one('ocean', 'tertiary_swell_wave_period', t('Tertiary swell period', 'Période de la houle tertiaire', 'Período del mar de fondo terciario', 'Período da ondulação terciária', 'فترة موج العباب الثالثي')),
	...one('ocean', 'ocean_u_current', t('Ocean current', 'Courant océanique', 'Corriente oceánica', 'Corrente oceânica', 'التيار المحيطي')),
	...one('ocean', 'sea_surface_temperature', t('Sea surface temperature', 'Température de surface de la mer', 'Temperatura superficial del mar', 'Temperatura da superfície do mar', 'درجة حرارة سطح البحر')),

	// Drought
	...soilLayers('drought', 'soil_moisture', (d, dAr) =>
		t(`Soil moisture (${d})`, `Humidité du sol (${d})`, `Humedad del suelo (${d})`, `Umidade do solo (${d})`, `رطوبة التربة (${dAr})`)),

	// Sub-seasonal (EC46 weekly means and anomalies)
	...one('temperature', 'temperature_2m_mean', t('Weekly mean 2-metre temperature', 'Température moyenne hebdomadaire à 2 m', 'Temperatura media semanal a 2 m', 'Temperatura média semanal a 2 m', 'متوسط درجة الحرارة الأسبوعي على ارتفاع 2 م')),
	...one('temperature', 'temperature_2m_anomaly', t('Weekly 2-metre temperature anomaly', 'Anomalie hebdomadaire de température à 2 m', 'Anomalía semanal de temperatura a 2 m', 'Anomalia semanal de temperatura a 2 m', 'شذوذ درجة الحرارة الأسبوعي على ارتفاع 2 م')),
	...one('temperature', 'dew_point_2m_mean', t('Weekly mean 2-metre dew point temperature', 'Point de rosée moyen hebdomadaire à 2 m', 'Punto de rocío medio semanal a 2 m', 'Ponto de orvalho médio semanal a 2 m', 'متوسط نقطة الندى الأسبوعي على ارتفاع 2 م')),
	...one('precipitation', 'precipitation_mean', t('Weekly mean precipitation', 'Précipitations moyennes hebdomadaires', 'Precipitación media semanal', 'Precipitação média semanal', 'متوسط الهطول الأسبوعي')),
	...one('precipitation', 'showers_mean', t('Weekly mean showers', 'Averses moyennes hebdomadaires', 'Chubascos medios semanales', 'Aguaceiros médios semanais', 'متوسط الزخات الأسبوعي')),
	...one('precipitation', 'snowfall_water_equivalent_mean', t('Weekly mean snowfall water equivalent', 'Équivalent en eau moyen hebdomadaire des chutes de neige', 'Equivalente en agua medio semanal de la nevada', 'Equivalente em água médio semanal da queda de neve', 'متوسط المكافئ المائي الأسبوعي لتساقط الثلوج')),
	...one('precipitation', 'snow_depth_water_equivalent_mean', t('Weekly mean snow depth water equivalent', 'Équivalent en eau moyen hebdomadaire du manteau neigeux', 'Equivalente en agua medio semanal de la nieve acumulada', 'Equivalente em água médio semanal da neve acumulada', 'متوسط المكافئ المائي الأسبوعي للغطاء الثلجي')),
	...one('atmosphere', 'pressure_msl_mean', t('Weekly mean sea level pressure', 'Pression moyenne hebdomadaire au niveau de la mer', 'Presión media semanal al nivel del mar', 'Pressão média semanal ao nível do mar', 'متوسط الضغط الأسبوعي عند مستوى سطح البحر')),
	...one('atmosphere', 'cloud_cover_mean', t('Weekly mean total cloud cover', 'Nébulosité totale moyenne hebdomadaire', 'Nubosidad total media semanal', 'Nebulosidade total média semanal', 'متوسط الغطاء السحابي الكلي الأسبوعي')),
	...one('atmosphere', 'total_column_integrated_water_vapour_mean', t('Weekly mean total column water vapour', 'Vapeur d’eau intégrée moyenne hebdomadaire', 'Vapor de agua total medio semanal en la columna', 'Vapor de água total médio semanal na coluna', 'متوسط بخار الماء الكلي الأسبوعي في العمود الجوي')),
	...one('ocean', 'sea_surface_temperature_mean', t('Weekly mean sea surface temperature', 'Température moyenne hebdomadaire de surface de la mer', 'Temperatura superficial del mar media semanal', 'Temperatura média semanal da superfície do mar', 'متوسط درجة حرارة سطح البحر الأسبوعي'))
];

const unknown = VARIABLES.filter((v) => !VARIABLE_NAMES.includes(v.name));
if (unknown.length) {
	console.warn(`Not in the package's variables, left out: ${unknown.map((v) => v.name).join(', ')}`);
}

// ── Domains ──────────────────────────────────────────────────────────────────

const byPrefix = (table, value) => table.find(([prefix]) => value.startsWith(prefix))?.[1];

const degrees = (value) => `${+value.toFixed(3)}°`;
const kilometres = (value) => `${+value.toFixed(1)} km`;

const getResolution = (domain) => {
	if (RESOLUTIONS[domain.value]) return RESOLUTIONS[domain.value];
	const { grid } = domain;
	if (grid.type === 'regular') {
		if (grid.dx) return degrees(grid.dx);
		return degrees((grid.longitude[1] - grid.longitude[0]) / (grid.nx - 1));
	}
	if (grid.dx) {
		// rotated lat/lon grids are spaced in degrees, the other projections in metres
		return grid.dx < 1 ? kilometres(grid.dx * 111.2) : kilometres(grid.dx / 1000);
	}
	throw new Error(`No resolution for ${domain.value}: add it to RESOLUTIONS`);
};

const perpendicularDistance = ([x, y], [x1, y1], [x2, y2]) => {
	const dx = x2 - x1;
	const dy = y2 - y1;
	const length = Math.hypot(dx, dy);
	if (!length) return Math.hypot(x - x1, y - y1);
	return Math.abs(dy * x - dx * y + x2 * y1 - y2 * x1) / length;
};

// Douglas-Peucker
const simplifyLine = (points, tolerance) => {
	if (points.length < 3) return points;
	let farthest = 0;
	let index = 0;
	for (let i = 1; i < points.length - 1; i++) {
		const distance = perpendicularDistance(points[i], points[0], points.at(-1));
		if (distance > farthest) [farthest, index] = [distance, i];
	}
	if (farthest <= tolerance) return [points[0], points.at(-1)];
	return [
		...simplifyLine(points.slice(0, index + 1), tolerance).slice(0, -1),
		...simplifyLine(points.slice(index), tolerance)
	];
};

// Closed [lon, lat] ring of the data, for the helper to compare with the
// country; null for the domains covering the whole globe.
const getCoverage = (domain) => {
	let ring = om.getDomainBoundary(domain);
	const start = ring[0];
	const end = ring.at(-1);
	// A ring around a pole comes back to its start one turn of longitude
	// further: close it over the pole so that it encloses the cap it covers.
	if (Math.abs(end[0] - start[0]) >= 359) {
		const pole = ring.reduce((sum, [, lat]) => sum + lat, 0) > 0 ? 90 : -90;
		ring = [...ring, [end[0], pole], [start[0], pole], start];
	}

	const lons = ring.map(([lon]) => lon);
	const lats = ring.map(([, lat]) => lat);
	const lonSpan = Math.max(...lons) - Math.min(...lons);
	const latSpan = Math.max(...lats) - Math.min(...lats);
	if (lonSpan >= 355 && latSpan >= 160) return null;

	// split the ring at its farthest point from the start, so both halves are open lines
	const distances = ring.map(([lon, lat]) => Math.hypot(lon - start[0], lat - start[1]));
	const far = distances.indexOf(Math.max(...distances));
	const simplified = [
		...simplifyLine(ring.slice(0, far + 1), COVERAGE_TOLERANCE).slice(0, -1),
		...simplifyLine([...ring.slice(far), start], COVERAGE_TOLERANCE)
	];
	return simplified.map(([lon, lat]) => [+lon.toFixed(2), +lat.toFixed(2)]);
};

const getKind = (value) => {
	if (value.startsWith('cams_')) return 'composition';
	if (value.startsWith('ecmwf_ec46') || value.startsWith('ecmwf_seas5')) return 'subseasonal';
	if (MARINE_DOMAINS.test(value)) return 'marine';
	return 'weather';
};

const getDocs = (value) => {
	if (MARINE_DOMAINS.test(value)) return `${DOCS}/marine-weather-api`;
	if (ENSEMBLE_DOMAINS.test(value)) return `${DOCS}/ensemble-api`;
	const page = byPrefix(PROVIDER_DOCS, value);
	return page ? `${DOCS}/${page}` : DOCS;
};

const DATE_FORMATS = { daily: 'yyyy-MM-dd', weekly_on_monday: 'yyyy-MM-dd', monthly: 'MMMM yyyy' };

const fetchLatest = async (value) => {
	try {
		const response = await fetch(`${BASE_URL}/${value}/latest.json`);
		if (!response.ok) throw new Error(`HTTP ${response.status}`);
		return await response.json();
	} catch (error) {
		console.warn(`${value}: no latest run (${error.message}), left out`);
		return null;
	}
};

const concreteDomains = om.domainOptions.filter((d) => !om.isSeamlessDomain(d));
const runs = await Promise.all(concreteDomains.map((d) => fetchLatest(d.value)));

const regional = [];
const domains = concreteDomains
	.map((domain, i) => ({ domain, latest: runs[i], coverage: runs[i] && getCoverage(domain) }))
	.filter(({ domain, latest, coverage }) => {
		if (!latest) return false;
		if (coverage && !includeRegional) {
			regional.push(domain.value);
			return false;
		}
		return true;
	})
	.map(({ domain, latest, coverage }) => {
		const { value } = domain;
		const region = coverage && byPrefix(DOMAIN_REGIONS, value);
		if (coverage && !region) throw new Error(`No region for ${value}: add it to DOMAIN_REGIONS`);
		return {
			value,
			label: LABELS[value] || domain.label.trim().replace(/^MF /, 'Météo-France '),
			provider: byPrefix(PROVIDERS, value),
			kind: getKind(value),
			coverage,
			region: coverage ? REGIONS[region] : GLOBAL,
			resolution: getResolution(domain),
			modelInterval: domain.model_interval,
			dateFormat: DATE_FORMATS[domain.time_interval],
			docs: getDocs(value),
			stored: new Set(latest.variables || [])
		};
	})
	// global models first
	.sort((a, b) => !!a.coverage - !!b.coverage);

if (regional.length) {
	console.log(`Regional models left out (--regional to include them): ${regional.join(', ')}`);
}

// ── Datasets ─────────────────────────────────────────────────────────────────

const buildDataset = (domain, variable) => {
	const title = mapLangs((lang) => `${variable.title[lang]} (${domain.label})`);
	const provider = `Open-Meteo / ${domain.provider}`;
	return {
		title,
		summary: mapLangs(() => `Open-Meteo — ${domain.provider}`),
		multi_temporal: true,
		public: true,
		enabled: false,
		current_time_method: 'next_to_now',
		auto_update_interval: AUTO_UPDATE_INTERVAL,
		metadata: {
			title,
			function: FUNCTIONS[domain.kind],
			resolution: domain.resolution,
			geographic_coverage: domain.region,
			source: provider,
			license: 'CC-BY-4.0',
			frequency_of_update: FREQUENCIES[domain.modelInterval],
			overview: overview(variable.title, domain.label, domain.provider, EVERY[domain.modelInterval]),
			learn_more: domain.docs
		},
		layers: [
			{
				type: 'openmeteo',
				title: variable.title,
				domain: domain.value,
				variable: variable.name,
				...(domain.dateFormat && { date_format: domain.dateFormat }),
				...(domain.coverage && { coverage: domain.coverage })
			}
		]
	};
};

// category key -> datasets, in VARIABLES order then domain order
const generated = new Map();
const stats = {};
for (const variable of VARIABLES) {
	for (const domain of domains) {
		if (!om.variableAvailable(variable.name, domain.stored)) continue;
		const category = domain.kind === 'subseasonal' ? 'climate' : variable.category;
		if (!generated.has(category)) generated.set(category, []);
		generated.get(category).push(buildDataset(domain, variable));
		stats[domain.value] = (stats[domain.value] || 0) + 1;
	}
}

// ── Catalog ──────────────────────────────────────────────────────────────────

const isGenerated = (dataset) =>
	dataset.layers?.length > 0 && dataset.layers.every((layer) => layer.type === 'openmeteo');

const catalog = JSON.parse(fs.readFileSync(CATALOG_PATH, 'utf8'));

for (const category of catalog.categories) {
	for (const subcategory of category.subcategories) {
		subcategory.datasets = subcategory.datasets.filter((dataset) => !isGenerated(dataset));
	}
	category.subcategories = category.subcategories.filter(
		(subcategory) => subcategory.datasets.length || !GENERATED_SUBCATEGORIES.includes(subcategory.title.en)
	);
}

for (const [key, datasets] of generated) {
	const category = catalog.categories.find((c) => c.title.en === CATEGORIES[key]);
	if (!category) throw new Error(`No "${CATEGORIES[key]}" category in the catalog`);
	const title = key === 'climate' ? SUBSEASONAL_SUBCATEGORY : SUBCATEGORY;
	let subcategory = category.subcategories.find((s) => s.title.en === title.en);
	if (!subcategory) {
		subcategory = { title, datasets: [] };
		category.subcategories.push(subcategory);
	}
	subcategory.datasets.push(...datasets);
}

const today = new Date().toISOString().slice(0, 10).replace(/-/g, '.');
catalog.version = option('--version') || today;

const total = Object.values(stats).reduce((sum, n) => sum + n, 0);
for (const [value, count] of Object.entries(stats)) console.log(`${value.padEnd(40)} ${count}`);
for (const [key, datasets] of generated) console.log(`${CATEGORIES[key].padEnd(40)} ${datasets.length}`);
console.log(`${total} Open-Meteo datasets from ${Object.keys(stats).length} models, catalog version ${catalog.version}`);

if (!dryRun) {
	fs.writeFileSync(CATALOG_PATH, JSON.stringify(catalog, null, 2) + '\n');
	console.log(`Written to ${CATALOG_PATH}`);
}

// the package keeps worker handles open
process.exit(0);
