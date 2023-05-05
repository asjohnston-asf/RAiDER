import datetime
import os
import xarray

import numpy as np

from herbie import Herbie
from pathlib import Path
from pyproj import CRS, Transformer
from shapely.geometry import Polygon

from RAiDER.utilFcns import round_date
from RAiDER.models.weatherModel import (
    WeatherModel, TIME_RES
)
from RAiDER.models.model_levels import (
    LEVELS_137_HEIGHTS,
)


class HRRR(WeatherModel):
    def __init__(self):
        # initialize a weather model
        super().__init__()

        self._humidityType = 'q'
        self._model_level_type = 'pl'  # Default, pressure levels are 'pl'
        self._expver = '0001'
        self._classname = 'hrrr'
        self._dataset = 'hrrr'

        self._time_res = TIME_RES[self._dataset.upper()]

        # Tuple of min/max years where data is available.
        self._valid_range = (datetime.datetime(2016, 7, 15), "Present")
        self._lag_time = datetime.timedelta(hours=3)  # Availability lag time in days

        # model constants
        self._k1 = 0.776  # [K/Pa]
        self._k2 = 0.233  # [K/Pa]
        self._k3 = 3.75e3  # [K^2/Pa]

        # 3 km horizontal grid spacing
        self._lat_res = 3. / 111
        self._lon_res = 3. / 111
        self._x_res = 3.
        self._y_res = 3.

        self._Nproc = 1
        self._Name = 'HRRR'
        self._Npl = 0
        self.files = None
        self._bounds = None
        self._zlevels = np.flipud(LEVELS_137_HEIGHTS)

        # Projection
        # NOTE: The HRRR projection will get read directly from the downloaded weather model file; however, 
        # we also define it here so that the projection can be used without downloading any data. This is 
        # used for consistency with the other weather models and allows for some nice features, such as 
        # buffering.
        # 
        # See https://github.com/blaylockbk/pyBKB_v2/blob/master/demos/HRRR_earthRelative_vs_gridRelative_winds.ipynb and code lower down
        # '262.5:38.5:38.5:38.5 237.280472:1799:3000.00 21.138123:1059:3000.00'
        # 'lov:latin1:latin2:latd lon1:nx:dx lat1:ny:dy'
        # LCC parameters
        lon0 = 262.5
        lat0 = 38.5
        lat1 = 38.5
        lat2 = 38.5
        x0 = 0
        y0 = 0
        earth_radius = 6371229
        p1 = CRS(f'+proj=lcc +lat_1={lat1} +lat_2={lat2} +lat_0={lat0} '\
                 f'+lon_0={lon0} +x_0={x0} +y_0={y0} +a={earth_radius} '\
                 f'+b={earth_radius} +units=m +no_defs')
        self._proj = p1

        self._valid_bounds =  Polygon(((-125, 21), (-133, 49), (-60, 49), (-72, 21)))



    def _fetch(self,  out):
        '''
        Fetch weather model data from HRRR
        '''
        self._files = out
        corrected_DT = round_date(self._time, datetime.timedelta(hours=self._time_res))
        if not corrected_DT == self._time:
            print('Rounded given datetime from  %s to %s', self._time, corrected_DT)

        if self.checkValidBounds(self._ll_bounds):
            self.checkTime(corrected_DT)
            download_hrrr_file(self._ll_bounds, corrected_DT, out, model='hrrr')
        else:
            hrrrak = HRRRAK()
            bounds = self._ll_bounds
            bounds[2:] = np.mod(bounds[2:], 360)
            if hrrrak.checkValidBounds(bounds):
                hrrrak.checkTime(corrected_DT)
                download_hrrr_file(self._ll_bounds, corrected_DT, out, model='hrrrak')
            else:
                raise ValueError('The requested location is unavailable for HRRR')
            

    def load_weather(self, *args, filename=None, **kwargs):
        '''
        Load a weather model into a python weatherModel object, from self.files if no
        filename is passed.
        '''
        if filename is None:
            filename = self.files[0] if isinstance(self.files, list) else self.files

        _xs, _ys, _lons, _lats, qs, temps, pl, geo_hgt = load_weather_hrrr(filename)
            # correct for latitude
        self._get_heights(_lats, geo_hgt)

        self._t = temps
        self._q = qs
        self._p = np.broadcast_to(pl[np.newaxis, np.newaxis, :],
                                    geo_hgt.shape)
        self._xs = _xs
        self._ys = _ys
        self._lats = _lats
        self._lons = _lons



class HRRRAK(WeatherModel):
    def __init__(self):
        # The HRRR-AK model has a few different parameters than HRRR-CONUS. 
        # These will get used if a user requests a bounding box in Alaska
        super().__init__()

        # model constants
        self._k1 = 0.776  # [K/Pa]
        self._k2 = 0.233  # [K/Pa]
        self._k3 = 3.75e3  # [K^2/Pa]

        # 3 km horizontal grid spacing
        self._lat_res = 3. / 111
        self._lon_res = 3. / 111
        self._x_res = 3.
        self._y_res = 3.

        self._Nproc = 1
        self._Npl = 0
        self.files = None
        self._bounds = None
        self._zlevels = np.flipud(LEVELS_137_HEIGHTS)

        self._classname = 'hrrrak'
        self._dataset = 'hrrrak'
        self._Name = "HRRR-AK"
        self._time_res = TIME_RES['HRRR-AK']
        self._valid_range = (datetime.datetime(2018, 7, 13), "Present")
        self._lag_time = datetime.timedelta(hours=3)
        self._valid_bounds =  Polygon(((195, 40), (157, 55), (175, 70), (260, 77), (232, 52)))

        # The projection information gets read directly from the  weather model file but we 
        # keep this here for object instantiation. 
        self._proj = CRS.from_string(
            '+proj=stere +ellps=sphere +a=6371229.0 +b=6371229.0 +lat_0=90 +lon_0=225.0 ' +
            '+x_0=0.0 +y_0=0.0 +lat_ts=60.0 +no_defs +type=crs'
        )
    def _fetch(self, out):
        bounds = self._ll_bounds.copy()
        bounds[2:] = np.mod(bounds[2:], 360)
        if self.checkValidBounds(bounds):
            corrected_DT = round_date(self._time, datetime.timedelta(hours=self._time_res))
            if not corrected_DT == self._time:
                print('Rounded given datetime from {} to {}'.format(self._time, corrected_DT))
            
            self.checkTime(corrected_DT)
            download_hrrr_file(self._ll_bounds, corrected_DT, out, model='hrrrak')

    def load_weather(self, *args, filename=None, **kwargs):
        if filename is None:
            filename = self.files[0] if isinstance(self.files, list) else self.files
        _xs, _ys, _lons, _lats, qs, temps, pl, geo_hgt = load_weather_hrrr(filename)
            # correct for latitude
        self._get_heights(_lats, geo_hgt)

        self._t = temps
        self._q = qs
        self._p = np.broadcast_to(pl[np.newaxis, np.newaxis, :],
                                    geo_hgt.shape)
        self._xs = _xs
        self._ys = _ys
        self._lats = _lats
        self._lons = _lons


def download_hrrr_file(ll_bounds, DATE, out, model='hrrr', product='prs', fxx=0, verbose=False):
    '''
    Download a HRRR weather model using Herbie

    Args: 
        DATE (Python datetime)  - Datetime as a Python datetime. Herbie will automatically return the closest valid time,
                                    which is currently hourly. 
        out (string)            - output location as a string
        model (string)          - model can be "hrrr" or "hrrrak"
        product (string)        - 'prs' for pressure levels, 'nat' for native levels
        fxx (int)               - forecast time in hours. Can be up to 48 for 00/06/12/18
        verbose (bool)          - True for extra printout of information
    
    Returns: 
        None, writes data to a netcdf file
    '''
    H = Herbie(
        DATE.strftime('%Y-%m-%d %H:%M'),
        model=model,
        product=product,
        fxx=fxx,
        overwrite=False,
        verbose=True,
        save_dir=Path(os.path.dirname(out)),
    )

    # Iterate through the list of datasets
    ds_list = H.xarray(":(SPFH|PRES|TMP|HGT):", verbose=verbose)
    ds_out = None
    for ds in ds_list:
        if ('isobaricInhPa' in ds._coord_names) or ('levels' in ds._coord_names):
            ds_out = ds
            break

    # bookkeepping
    ds_out = ds_out.assign_coords(longitude=(((ds_out.longitude + 180) % 360) - 180))
    ds_out = ds_out.rename({'gh': 'z', 'isobaricInhPa': 'levels'})

    # projection information
    ds_out["proj"] = int()
    for k, v in CRS.from_user_input(ds.herbie.crs).to_cf().items():
        ds_out.proj.attrs[k] = v
    for var in ds_out.data_vars:
        ds_out[var].attrs['grid_mapping'] = 'proj'

    # subset the full file by AOI
    x_min, x_max, y_min, y_max = get_bounds_indices(
        ll_bounds, 
        ds_out.latitude.to_numpy(), 
        ds_out.longitude.to_numpy(),
    )
    ds_out = ds_out.sel(x=slice(x_min, x_max), y=slice(y_min, y_max))

    # transform coordinates. HRRR uses pixel index as the base coordinate, but 
    # I need actual coordinates later on to do the interpolation
    t = Transformer.from_crs(CRS.from_epsg(4326), ds_out.herbie.crs)
    x,y = t.transform(ds_out.latitude, ds_out.longitude)
    x = np.mean(x,axis=0).copy()
    y = np.mean(y,axis=1).copy()
    ds_out['x'] = x
    ds_out['y'] = y
    
    # Write to a NETCDF file
    ds_out.to_netcdf(out, engine='netcdf4')

    return


def get_bounds_indices(SNWE, lats, lons):
    '''
    Convert SNWE lat/lon bounds to index bounds
    '''
    # Unpack the bounds and find the relevent indices 
    S, N, W, E = SNWE
    m1 = (S <= lats) & (N >= lats) & (W <= lons) & (E >= lons)

    if np.sum(m1) == 0:
        lons = np.mod(lons, 360)
        W, E = np.mod([W, E], 360)
        m1 = (S <= lats) & (N >= lats) & (W <= lons) & (E >= lons)
        if np.sum(m1) == 0:
            raise RuntimeError('Area of Interest has no overlap with the HRRR model available extent')

    # Y extent
    shp = lats.shape
    m1_y = np.argwhere(np.sum(m1, axis=1) != 0)
    y_min = max(m1_y[0][0], 0)
    y_max = min(m1_y[-1][0], shp[0])
    m1_y = None

    # X extent
    m1_x = np.argwhere(np.sum(m1, axis=0) != 0)
    x_min = max(m1_x[0][0], 0)
    x_max = min(m1_x[-1][0], shp[1])
    m1_x = None
    m1 = None

    return x_min, x_max, y_min, y_max


def load_weather_hrrr(filename):
    '''
    Loads a weather model from a HRRR file
    '''
    # read data from the netcdf file
    ds = xarray.open_dataset(filename, engine='netcdf4')

    # Pull the relevant data from the file
    pl = np.array([p * 100 for p in ds.levels.values]) # convert millibars to Pascals
    xArr = ds['x'].values
    yArr = ds['y'].values
    lats = ds['latitude'].values
    lons = ds['longitude'].values
    temps = ds['t'].values.transpose(1, 2, 0)
    qs = ds['q'].values.transpose(1, 2, 0)
    geo_hgt = ds['z'].values.transpose(1, 2, 0)

    lons[lons > 180] -= 360

    # data cube format should be lats,lons,heights
    _xs = np.broadcast_to(xArr[np.newaxis, :, np.newaxis],
                            geo_hgt.shape)
    _ys = np.broadcast_to(yArr[:, np.newaxis, np.newaxis],
                            geo_hgt.shape)
    _lons = np.broadcast_to(lons[..., np.newaxis],
                            geo_hgt.shape)
    _lats = np.broadcast_to(lats[..., np.newaxis],
                            geo_hgt.shape)

    return _xs, _ys, _lons, _lats, qs, temps, pl, geo_hgt