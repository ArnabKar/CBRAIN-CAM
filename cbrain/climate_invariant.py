from cbrain.imports import *
from cbrain.utils import *
from cbrain.layers import *
from cbrain.data_generator import DataGenerator
from tensorflow.keras.layers import *
from tensorflow.keras.models import *
from cbrain.cam_constants import *
from tensorflow.keras.layers import *
from tensorflow.keras import layers
import enum
from tensorflow import math as tfm
# import tensorflow_probability as tfp
import yaml
import pickle
import scipy.integrate as sin

path = '/export/nfs0home/tbeucler/CBRAIN-CAM/cbrain/'
path_hyam = 'hyam_hybm.pkl'

hf = open(path+path_hyam,'rb')
hyam,hybm = pickle.load(hf)

################################### Tensorflow Versions ##############################################

################### Q2VRH and T2TNS Layers ########################################


def eliq(T):
    a_liq = np.float32(np.array([-0.976195544e-15,-0.952447341e-13,\
                                 0.640689451e-10,\
                      0.206739458e-7,0.302950461e-5,0.264847430e-3,\
                      0.142986287e-1,0.443987641,6.11239921]));
    c_liq = np.float32(-80.0)
    T0 = np.float32(273.16)
    return np.float32(100.0)*tfm.polyval(a_liq,tfm.maximum(c_liq,T-T0))

def eice(T):
    a_ice = np.float32(np.array([0.252751365e-14,0.146898966e-11,0.385852041e-9,\
                      0.602588177e-7,0.615021634e-5,0.420895665e-3,\
                      0.188439774e-1,0.503160820,6.11147274]));
    c_ice = np.float32(np.array([273.15,185,-100,0.00763685,0.000151069,7.48215e-07]))
    T0 = np.float32(273.16)
    return tf.where(T>c_ice[0],eliq(T),\
                   tf.where(T<=c_ice[1],np.float32(100.0)*(c_ice[3]+tfm.maximum(c_ice[2],T-T0)*\
                   (c_ice[4]+tfm.maximum(c_ice[2],T-T0)*c_ice[5])),\
                           np.float32(100.0)*tfm.polyval(a_ice,T-T0)))

def esat(T):
    T0 = np.float32(273.16)
    T00 = np.float32(253.16)
    omtmp = (T-T00)/(T0-T00)
    omega = tfm.maximum(np.float32(0.0),tfm.minimum(np.float32(1.0),omtmp))

    return tf.where(T>T0,eliq(T),tf.where(T<T00,eice(T),(omega*eliq(T)+(1-omega)*eice(T))))

def qv(T,RH,P0,PS,hyam,hybm):

    R = np.float32(287.0)
    Rv = np.float32(461.0)
    p = P0 * hyam + PS[:, None] * hybm # Total pressure (Pa)

    T = tf.cast(T,tf.float32)
    RH = tf.cast(RH,tf.float32)
    p = tf.cast(p,tf.float32)

    return R*esat(T)*RH/(Rv*p)
    # DEBUG 1
    # return esat(T)

def RH(T,qv,P0,PS,hyam,hybm):
    R = np.float32(287.0)
    Rv = np.float32(461.0)
    p = P0 * hyam + PS[:, None] * hybm # Total pressure (Pa)

    T = tf.cast(T,tf.float32)
    qv = tf.cast(qv,tf.float32)
    p = tf.cast(p,tf.float32)

    return Rv*p*qv/(R*esat(T))

def qsat(T,P0,PS,hyam,hybm):
    return qv(T,1,P0,PS,hyam,hybm)



def dP(PS):
    S = PS.shape
    P = 1e5 * np.tile(hyai,(S[0],1))+np.transpose(np.tile(PS,(31,1)))*np.tile(hybi,(S[0],1))
    return P[:, 1:]-P[:, :-1]




###################################### QV2RH and T2TNS layer ##############################################

class QV2RH(Layer):
    def __init__(self, inp_subQ, inp_divQ, inp_subRH, inp_divRH, hyam, hybm, **kwargs):
        """
        Call using ([input])
        Assumes
        prior: [QBP,
        TBP, PS, SOLIN, SHFLX, LHFLX]
        Returns
        post(erior): [RHBP,
        TBP, PS, SOLIN, SHFLX, LHFLX]
        Arguments:
        inp_subQ = Normalization based on input with specific humidity (subtraction constant)
        inp_divQ = Normalization based on input with specific humidity (division constant)
        inp_subRH = Normalization based on input with relative humidity (subtraction constant)
        inp_divRH = Normalization based on input with relative humidity (division constant)
        hyam = Constant a for pressure based on mid-levels
        hybm = Constant b for pressure based on mid-levels
        """
        self.inp_subQ, self.inp_divQ, self.inp_subRH, self.inp_divRH, self.hyam, self.hybm = \
            np.array(inp_subQ), np.array(inp_divQ), np.array(inp_subRH), np.array(inp_divRH), \
        np.array(hyam), np.array(hybm)
        # Define variable indices here
        # Input
        self.QBP_idx = slice(0,30)
        self.TBP_idx = slice(30,60)
        self.PS_idx = 60
        self.SHFLX_idx = 62
        self.LHFLX_idx = 63

        super().__init__(**kwargs)

    def build(self, input_shape):
        super().build(input_shape)

    def get_config(self):
        config = {'inp_subQ': list(self.inp_subQ), 'inp_divQ': list(self.inp_divQ),
                  'inp_subRH': list(self.inp_subRH), 'inp_divRH': list(self.inp_divRH),
                  'hyam': list(self.hyam),'hybm': list(self.hybm)}
        base_config = super().get_config()
        return dict(list(base_config.items()) + list(config.items()))

    def call(self, arrs):
        prior = arrs

        Tprior = prior[:,self.TBP_idx]*self.inp_divQ[self.TBP_idx]+self.inp_subQ[self.TBP_idx]
        qvprior = prior[:,self.QBP_idx]*self.inp_divQ[self.QBP_idx]+self.inp_subQ[self.QBP_idx]
        PSprior = prior[:,self.PS_idx]*self.inp_divQ[self.PS_idx]+self.inp_subQ[self.PS_idx]
        RHprior = (RH(Tprior,qvprior,P0,PSprior,self.hyam,self.hybm)-\
                    self.inp_subRH[self.QBP_idx])/self.inp_divRH[self.QBP_idx]

        post = tf.concat([tf.cast(RHprior,tf.float32),prior[:,30:]], axis=1)

        return post

    def compute_output_shape(self,input_shape):
        """Input shape + 1"""
        return (input_shape[0][0])


class T2TmTNS(Layer):
    def __init__(self, inp_subT, inp_divT, inp_subTNS, inp_divTNS, hyam, hybm, **kwargs):
        """
        From temperature to (temperature)-(near-surface temperature)
        Call using ([input])
        Assumes
        prior: [QBP,
        TBP,
        PS, SOLIN, SHFLX, LHFLX]
        Returns
        post(erior): [QBP,
        TfromNS,
        PS, SOLIN, SHFLX, LHFLX]
        Arguments:
        inp_subT = Normalization based on input with temperature (subtraction constant)
        inp_divT = Normalization based on input with temperature (division constant)
        inp_subTNS = Normalization based on input with (temp - near-sur temp) (subtraction constant)
        inp_divTNS = Normalization based on input with (temp - near-sur temp) (division constant)
        hyam = Constant a for pressure based on mid-levels
        hybm = Constant b for pressure based on mid-levels
        """
        self.inp_subT, self.inp_divT, self.inp_subTNS, self.inp_divTNS, self.hyam, self.hybm = \
            np.array(inp_subT), np.array(inp_divT), np.array(inp_subTNS), np.array(inp_divTNS), \
        np.array(hyam), np.array(hybm)
        # Define variable indices here
        # Input
        self.QBP_idx = slice(0,30)
        self.TBP_idx = slice(30,60)
        self.PS_idx = 60
        self.SHFLX_idx = 62
        self.LHFLX_idx = 63

        super().__init__(**kwargs)

    def build(self, input_shape):
        super().build(input_shape)

    def get_config(self):
        config = {'inp_subT': list(self.inp_subT), 'inp_divT': list(self.inp_divT),
                  'inp_subTNS': list(self.inp_subTNS), 'inp_divTNS': list(self.inp_divTNS),
                  'hyam': list(self.hyam),'hybm': list(self.hybm)}
        base_config = super().get_config()
        return dict(list(base_config.items()) + list(config.items()))

    def call(self, arrs):
        prior = arrs

        Tprior = prior[:,self.TBP_idx]*self.inp_divT[self.TBP_idx]+self.inp_subT[self.TBP_idx]

        Tile_dim = tf.constant([1,30],tf.int32)
        TNSprior = ((Tprior-tf.tile(tf.expand_dims(Tprior[:,-1],axis=1),Tile_dim))-\
                    self.inp_subTNS[self.TBP_idx])/\
        self.inp_divTNS[self.TBP_idx]

        post = tf.concat([prior[:,:30],tf.cast(TNSprior,tf.float32),prior[:,60:]], axis=1)

        return post

    def compute_output_shape(self,input_shape):
        """Input shape + 1"""
        return (input_shape[0][0])


######################################## Scale operation Layer  ############################################

class OpType(enum.Enum):
    LH_SH=-1
    PWA=0
    LHFLX=1
    PWA_PARTIAL=2
    PWA_PARTIAL_2 = 3 #raise to 0.75


class ScaleOp(layers.Layer):
    #if index = -1 that means take shflx+lhflx
    def __init__(self,index,inp_subQ, inp_divQ,**kwargs):
        self.scaling_index = index
        self.inp_subQ, self.inp_divQ =  np.array(inp_subQ), np.array(inp_divQ)
        super(ScaleOp,self).__init__(**kwargs)


    def get_config(self):
        config = {'index':self.scaling_index,'inp_subQ': list(self.inp_subQ), 'inp_divQ': list(self.inp_divQ)}
        base_config = super().get_config()
        return dict(list(base_config.items()) + list(config.items()))


    def call(self,inps):
        inp,op = inps
        #for scaling using LHFLX+SHFLX
        if self.scaling_index==OpType.LH_SH.value:
            scaling_factor = (inp[:,62]*self.inp_divQ[62] + self.inp_subQ[62]) + (inp[:,63]*self.inp_divQ[63] + self.inp_subQ[63])
            op_updated = op[:,:60] * tf.expand_dims(scaling_factor,1)

        elif self.scaling_index==OpType.PWA.value:
            scaling_factor = inp[:,64]
            op_updated = op[:,:60] * tf.expand_dims(scaling_factor,1)

        elif self.scaling_index==OpType.LHFLX.value:
            scaling_factor = inp[:,63]*self.inp_divQ[63] + self.inp_subQ[63]
            op_updated = op[:,:60] * tf.expand_dims(scaling_factor,1)

        elif self.scaling_index==OpType.PWA_PARTIAL.value:
            scaling_factor = inp[:,64]
            con_moi = op[:,:30] * tf.expand_dims(scaling_factor**0.5,1)
            con_heat = op[:,30:60] / tf.expand_dims(scaling_factor**0.5,1)
            op_updated = tf.concat((con_moi,con_heat),axis=1)

        elif self.scaling_index==OpType.PWA_PARTIAL_2.value:
            scaling_factor = inp[:,64]
            con_moi = op[:,:30] * tf.expand_dims(scaling_factor**0.75,1)
            con_heat = op[:,30:60] / tf.expand_dims(scaling_factor**0.75,1)
            op_updated = tf.concat((con_moi,con_heat),axis=1)

        op_rest = op[:,60:]
        op = tf.concat((op_updated,op_rest),axis=1)
        return op




######################################## Reverse Interpolation Layer  ############################################

class reverseInterpLayer(layers.Layer):
    '''
        returns the values of pressure and temperature in the original coordinate system
        input - batch_size X (tilde_dimen*2+4) --- 84 in this case
        output - batch_size X 64
        original lev_tilde = batch_size x 30
        x_ref_min - batch_size x 1
        x_ref_max - batch_size x 1
        y_ref - batch_size x interim_dim
    '''
    def __init__(self,interim_dim_size, **kwargs):
        self.interim_dim_size = interim_dim_size #40 for starting
        super(reverseInterpLayer,self).__init__(**kwargs)



    def get_config(self):
        config = {"interim_dim_size":self.interim_dim_size}
        base_config = super().get_config()
        return dict(list(base_config.items()) + list(config.items()))



    def call(self,inputs):
        X = inputs[0]
        X_original = inputs[1] #batch_size X 30, lev_tilde_before
        x_ref_min = tf.fill(value=0.0,dims=[tf.shape(X)[0],])
        x_ref_max = tf.fill(value=1.4,dims=[tf.shape(X)[0],])
        y_ref_pressure = X[:,:self.interim_dim_size]
        y_ref_temperature = X[:,self.interim_dim_size:2*self.interim_dim_size]
        y_pressure = tfp.math.batch_interp_regular_1d_grid(X_original,x_ref_min,x_ref_max,y_ref_pressure)
        y_temperature = tfp.math.batch_interp_regular_1d_grid(X_original,x_ref_min,x_ref_max,y_ref_temperature)
        y_tilde_before = tf.concat([y_pressure,y_temperature,X[:,2*self.interim_dim_size:]], axis=1)
        return y_tilde_before




#################################################################################################################


























################################### Numpy Versions ##############################################


################### Q2VRH and T2TNS Layers ########################################

class CrhClass:
    def __init__(self):
        pass

    def eliq(self,T):
        a_liq = np.array([-0.976195544e-15,-0.952447341e-13,0.640689451e-10,0.206739458e-7,0.302950461e-5,0.264847430e-3,0.142986287e-1,0.443987641,6.11239921]);
        c_liq = -80
        T0 = 273.16
        return 100*np.polyval(a_liq,np.maximum(c_liq,T-T0))

    def eice(self,T):
        a_ice = np.array([0.252751365e-14,0.146898966e-11,0.385852041e-9,0.602588177e-7,0.615021634e-5,0.420895665e-3,0.188439774e-1,0.503160820,6.11147274]);
        c_ice = np.array([273.15,185,-100,0.00763685,0.000151069,7.48215e-07])
        T0 = 273.16
        return (T>c_ice[0])*self.eliq(T)+\
    (T<=c_ice[0])*(T>c_ice[1])*100*np.polyval(a_ice,T-T0)+\
    (T<=c_ice[1])*100*(c_ice[3]+np.maximum(c_ice[2],T-T0)*(c_ice[4]+np.maximum(c_ice[2],T-T0)*c_ice[5]))

    def esat(self,T):
        T0 = 273.16
        T00 = 253.16
        omega = np.maximum(0,np.minimum(1,(T-T00)/(T0-T00)))

        return (T>T0)*self.eliq(T)+(T<T00)*self.eice(T)+(T<=T0)*(T>=T00)*(omega*self.eliq(T)+(1-omega)*self.eice(T))

    def RH(self,T,qv,P0,PS,hyam,hybm):
        R = 287
        Rv = 461
        S = PS.shape
        p = 1e5 * np.tile(hyam,(S[0],1))+np.transpose(np.tile(PS,(30,1)))*np.tile(hybm,(S[0],1))

        return Rv*p*qv/(R*self.esat(T))

    def qv(self,T,RH,P0,PS,hyam,hybm):
        R = 287
        Rv = 461
        S = PS.shape
        p = 1e5 * np.tile(hyam,(S[0],1))+np.transpose(np.tile(PS,(30,1)))*np.tile(hybm,(S[0],1))

        return R*self.esat(T)*RH/(Rv*p)


    def qsat(self,T,P0,PS,hyam,hybm):
        return self.qv(T,1,P0,PS,hyam,hybm)



    def dP(self,PS):
        S = PS.shape
        P = 1e5 * np.tile(hyai,(S[0],1))+np.transpose(np.tile(PS,(31,1)))*np.tile(hybi,(S[0],1))
        return P[:, 1:]-P[:, :-1]


class ThermLibNumpy:
    @staticmethod
    def eliqNumpy(T):
        a_liq = np.float32(np.array([-0.976195544e-15,-0.952447341e-13,\
                                     0.640689451e-10,\
                          0.206739458e-7,0.302950461e-5,0.264847430e-3,\
                          0.142986287e-1,0.443987641,6.11239921]));
        c_liq = np.float32(-80.0)
        T0 = np.float32(273.16)
        return np.float32(100.0)*np.polyval(a_liq,np.maximum(c_liq,T-T0))


    @staticmethod
    def eiceNumpy(T):
        a_ice = np.float32(np.array([0.252751365e-14,0.146898966e-11,0.385852041e-9,\
                          0.602588177e-7,0.615021634e-5,0.420895665e-3,\
                          0.188439774e-1,0.503160820,6.11147274]));
        c_ice = np.float32(np.array([273.15,185,-100,0.00763685,0.000151069,7.48215e-07]))
        T0 = np.float32(273.16)
        return np.where(T>c_ice[0],ThermLibNumpy.eliqNumpy(T),\
                       np.where(T<=c_ice[1],np.float32(100.0)*(c_ice[3]+np.maximum(c_ice[2],T-T0)*\
                       (c_ice[4]+np.maximum(c_ice[2],T-T0)*c_ice[5])),\
                               np.float32(100.0)*np.polyval(a_ice,T-T0)))

    @staticmethod
    def esatNumpy(T):
        T0 = np.float32(273.16)
        T00 = np.float32(253.16)
        omtmp = (T-T00)/(T0-T00)
        omega = np.maximum(np.float32(0.0),np.minimum(np.float32(1.0),omtmp))

        return np.where(T>T0,ThermLibNumpy.eliqNumpy(T),np.where(T<T00,ThermLibNumpy.eiceNumpy(T),(omega*ThermLibNumpy.eliqNumpy(T)+(1-omega)*ThermLibNumpy.eiceNumpy(T))))

    @staticmethod
    def qvNumpy(T,RH,P0,PS,hyam,hybm):

        R = np.float32(287.0)
        Rv = np.float32(461.0)
        p = P0 * hyam + PS[:, None] * hybm # Total pressure (Pa)

        T = T.astype(np.float32)
        if type(RH) == int:
            RH = T**0
        RH = RH.astype(np.float32)
        p = p.astype(np.float32)

        return R*ThermLibNumpy.esatNumpy(T)*RH/(Rv*p)
        # DEBUG 1
        # return esat(T)

    @staticmethod
    def RHNumpy(T,qv,P0,PS,hyam,hybm):
        R = np.float32(287.0)
        Rv = np.float32(461.0)
        p = P0 * hyam + PS[:, None] * hybm # Total pressure (Pa)

        T = T.astype(np.float32)
        qv = qv.astype(np.float32)
        p = p.astype(np.float32)

        return Rv*p*qv/(R*ThermLibNumpy.esatNumpy(T))


    @staticmethod
    def qsatNumpy(T,P0,PS,hyam,hybm):
        return ThermLibNumpy.qvNumpy(T,1,P0,PS,hyam,hybm)


    @staticmethod
    def qsatsurfNumpy(TS,P0,PS):
        R = 287
        Rv = 461
        return R*ThermLibNumpy.esatNumpy(TS)/(Rv*PS)

    @staticmethod
    def dPNumpy(PS):
        S = PS.shape
        P = 1e5 * np.tile(hyai,(S[0],1))+np.transpose(np.tile(PS,(31,1)))*np.tile(hybi,(S[0],1))
        return P[:, 1:]-P[:, :-1]
    
    @staticmethod
    def theta_e_calc(T,qv,P0,PS,hyam,hybm):
        S = PS.shape
        p = P0 * np.tile(hyam,(S[0],1))+np.transpose(np.tile(PS,(30,1)))*np.tile(hybm,(S[0],1))
        tmelt  = 273.15
        CPD = 1005.7
        CPV = 1870.0
        CPVMCL = 2320.0
        RV = 461.5
        RD = 287.04
        EPS = RD/RV
        ALV0 = 2.501E6
        r = qv / (1. - qv)
        # get ev in hPa 
        ev_hPa = 100*p*r/(EPS+r)
        #get TL
        TL = (2840. / ((3.5*np.log(T)) - (np.log(ev_hPa)) - 4.805)) + 55.
        #calc chi_e:
        chi_e = 0.2854 * (1. - (0.28*r))
        P0_norm = (P0/(P0 * np.tile(hyam,(S[0],1))+np.transpose(np.tile(PS,(30,1)))*np.tile(hybm,(S[0],1))))
        theta_e = T * P0_norm**chi_e * np.exp(((3.376/TL) - 0.00254) * r * 1000. * (1. + (0.81 * r)))
        return theta_e
    
    @staticmethod
    def theta_e_sat_calc(T,P0,PS,hyam,hybm):
        return ThermLibNumpy.theta_e_calc(T,ThermLibNumpy.qsatNumpy(T,P0,PS,hyam,hybm),P0,PS,hyam,hybm) 
    
    @staticmethod
    def bmse_calc(T,qv,P0,PS,hyam,hybm):
        eps = 0.622 # Ratio of molecular weight(H2O)/molecular weight(dry air)
        R_D = 287 # Specific gas constant of dry air in J/K/kg
        Rv = 461
        # Calculate kappa
        QSAT0 = ThermLibNumpy.qsatNumpy(T,P0,PS,hyam,hybm)
        kappa = 1+(L_V**2)*QSAT0/(Rv*C_P*(T**2))
        # Calculate geopotential
        r = qv/(qv**0-qv)
        Tv = T*(r**0+r/eps)/(r**0+r)
        p = P0 * hyam + PS[:, None] * hybm
        p = p.astype(np.float32)
        RHO = p/(R_D*Tv)
        Z = -sin.cumtrapz(x=p,y=1/(G*RHO),axis=1)
        Z = np.concatenate((0*Z[:,0:1]**0,Z),axis=1)
        # Assuming near-surface is at 2 meters
        Z = (Z-Z[:,[29]])+2 
        # Calculate MSEs of plume and environment
        Tile_dim = [1,30]
        h_plume = np.tile(np.expand_dims(C_P*T[:,-1]+L_V*qv[:,-1],axis=1),Tile_dim)
        h_satenv = C_P*T+L_V*qv+G*Z
        return (G/kappa)*(h_plume-h_satenv)/(C_P*T)

class QV2RHNumpy:
    def __init__(self, inp_sub, inp_div, inp_subRH, inp_divRH, hyam, hybm):
        self.inp_sub, self.inp_div, self.inp_subRH, self.inp_divRH, self.hyam, self.hybm = \
            np.array(inp_sub), np.array(inp_div), np.array(inp_subRH), np.array(inp_divRH), \
        np.array(hyam), np.array(hybm)
        # Define variable indices here
        # Input
        self.QBP_idx = slice(0,30)
        self.TBP_idx = slice(30,60)
        self.PS_idx = 60
        self.SHFLX_idx = 62
        self.LHFLX_idx = 63
    def process(self,X):
        Tprior = X[:,self.TBP_idx]*self.inp_div[self.TBP_idx]+self.inp_sub[self.TBP_idx]
        qvprior = X[:,self.QBP_idx]*self.inp_div[self.QBP_idx]+self.inp_sub[self.QBP_idx]
        PSprior = X[:,self.PS_idx]*self.inp_div[self.PS_idx]+self.inp_sub[self.PS_idx]
        RHprior = (ThermLibNumpy.RHNumpy(Tprior,qvprior,P0,PSprior,self.hyam,self.hybm)-\
                    self.inp_subRH[self.QBP_idx])/self.inp_divRH[self.QBP_idx]
        X_result = np.concatenate([RHprior.astype(np.float32),X[:,30:]], axis=1)
        return X_result
class QV2QSATdeficitNumpy:
    def __init__(self, inp_sub, inp_div, inp_subQ, inp_divQ, hyam, hybm):
        self.inp_sub, self.inp_div, self.inp_subQ, self.inp_divQ, self.hyam, self.hybm = \
            np.array(inp_sub), np.array(inp_div), np.array(inp_subQ), np.array(inp_divQ), \
        np.array(hyam), np.array(hybm)
        # Define variable indices here
        # Input
        self.QBP_idx = slice(0,30)
        self.TBP_idx = slice(30,60)
        self.PS_idx = 60
        self.SHFLX_idx = 62
        self.LHFLX_idx = 63
    def process(self,X):
        Tprior = X[:,self.TBP_idx]*self.inp_div[self.TBP_idx]+self.inp_sub[self.TBP_idx]
        qvprior = X[:,self.QBP_idx]*self.inp_div[self.QBP_idx]+self.inp_sub[self.QBP_idx]
        PSprior = X[:,self.PS_idx]*self.inp_div[self.PS_idx]+self.inp_sub[self.PS_idx]
        QSATdeficitprior = (ThermLibNumpy.qsatNumpy(Tprior,P0,PSprior,self.hyam,self.hybm)-\
                            qvprior-self.inp_subQ[self.QBP_idx])/self.inp_divQ[self.QBP_idx]
        X_result = np.concatenate([QSATdeficitprior.astype(np.float32),X[:,30:]], axis=1)
        return X_result
class T2TmTNSNumpy:
    def __init__(self, inp_sub, inp_div, inp_subTNS, inp_divTNS, hyam, hybm):
        self.inp_sub, self.inp_div, self.inp_subTNS, self.inp_divTNS, self.hyam, self.hybm = \
            np.array(inp_sub), np.array(inp_div), np.array(inp_subTNS), np.array(inp_divTNS), \
        np.array(hyam), np.array(hybm)
        # Define variable indices here
        # Input
        self.QBP_idx = slice(0,30)
        self.TBP_idx = slice(30,60)
        self.PS_idx = 60
        self.SHFLX_idx = 62
        self.LHFLX_idx = 63
    def process(self,X):
        Tprior = X[:,self.TBP_idx]*self.inp_div[self.TBP_idx]+self.inp_sub[self.TBP_idx]
        Tile_dim = [1,30]
        TNSprior = ((Tprior-np.tile(np.expand_dims(Tprior[:,-1],axis=1),Tile_dim))-\
                    self.inp_subTNS[self.TBP_idx])/\
        self.inp_divTNS[self.TBP_idx]
        post = np.concatenate([X[:,:30],TNSprior.astype(np.float32),X[:,60:]], axis=1)
        X_result = post
        return X_result
class T2BCONSNumpy:
    def __init__(self, inp_sub, inp_div, inp_subT, inp_divT, hyam, hybm):
        self.inp_sub, self.inp_div, self.inp_subT, self.inp_divT, self.hyam, self.hybm = \
            np.array(inp_sub), np.array(inp_div), np.array(inp_subT), np.array(inp_divT), \
        np.array(hyam), np.array(hybm)
        # Define variable indices here
        # Input
        self.QBP_idx = slice(0,30)
        self.TBP_idx = slice(30,60)
        self.PS_idx = 60
        self.SHFLX_idx = 62
        self.LHFLX_idx = 63
    def process(self,X):
        Tprior = X[:,self.TBP_idx]*self.inp_div[self.TBP_idx]+self.inp_sub[self.TBP_idx]
        qvprior = X[:,self.QBP_idx]*self.inp_div[self.QBP_idx]+self.inp_sub[self.QBP_idx]
        PSprior = X[:,self.PS_idx]*self.inp_div[self.PS_idx]+self.inp_sub[self.PS_idx]
        theta = ThermLibNumpy.theta_e_calc(Tprior,qvprior,P0,PSprior,self.hyam,self.hybm)
        Tile_dim = [1,30]
        thetaS = ThermLibNumpy.theta_e_calc(Tprior,qvprior,P0,PSprior,self.hyam,self.hybm)[:,-1]
        Bcons = G*(np.tile(np.expand_dims(thetaS,axis=1),Tile_dim)-\
                   ThermLibNumpy.theta_e_sat_calc(Tprior,P0,PSprior,self.hyam,self.hybm))/\
        ThermLibNumpy.theta_e_sat_calc(Tprior,P0,PSprior,self.hyam,self.hybm)
        Bconsprior = (Bcons-self.inp_subT[self.TBP_idx])/self.inp_divT[self.TBP_idx]
        post = np.concatenate([X[:,:30],Bconsprior.astype(np.float32),X[:,60:]], axis=1)
        X_result = post
        return X_result
class T2BMSENumpy:
    def __init__(self, inp_sub, inp_div, inp_subT, inp_divT, hyam, hybm):
        self.inp_sub, self.inp_div, self.inp_subT, self.inp_divT, self.hyam, self.hybm = \
            np.array(inp_sub), np.array(inp_div), np.array(inp_subT), np.array(inp_divT), \
        np.array(hyam), np.array(hybm)
        # Define variable indices here
        # Input
        self.QBP_idx = slice(0,30)
        self.TBP_idx = slice(30,60)
        self.PS_idx = 60
        self.SHFLX_idx = 62
        self.LHFLX_idx = 63
    def process(self,X):
        Tprior = X[:,self.TBP_idx]*self.inp_div[self.TBP_idx]+self.inp_sub[self.TBP_idx]
        qvprior = X[:,self.QBP_idx]*self.inp_div[self.QBP_idx]+self.inp_sub[self.QBP_idx]
        PSprior = X[:,self.PS_idx]*self.inp_div[self.PS_idx]+self.inp_sub[self.PS_idx]
        Bmse = ThermLibNumpy.bmse_calc(Tprior,qvprior,P0,PSprior,self.hyam,self.hybm)
        Bmseprior = (Bmse-self.inp_subT[self.TBP_idx])/self.inp_divT[self.TBP_idx]
        post = np.concatenate([X[:,:30],Bmseprior.astype(np.float32),X[:,60:]], axis=1)
        X_result = post
        return X_result
class T2T_NSto220Numpy:
    def __init__(self, inp_sub, inp_div, inp_subTNS220, inp_divTNS220, hyam, hybm):
        self.inp_sub, self.inp_div, self.inp_subTNS220, self.inp_divTNS220, self.hyam, self.hybm = \
            np.array(inp_sub), np.array(inp_div), np.array(inp_subTNS220), np.array(inp_divTNS220), \
        np.array(hyam), np.array(hybm)
        # Define variable indices here
        # Input
        self.QBP_idx = slice(0,30)
        self.TBP_idx = slice(30,60)
        self.PS_idx = 60
        self.SHFLX_idx = 62
        self.LHFLX_idx = 63
        self.T_trop = 220 # In K
    
    def process(self,X):
        Tprior = X[:,self.TBP_idx]*self.inp_div[self.TBP_idx]+self.inp_sub[self.TBP_idx]

        Tile_dim = [1,30]
        TNS = np.tile(np.expand_dims(Tprior[:,-1],axis=1),Tile_dim)
        TNS220tonorm = (TNS-Tprior)/(TNS-self.T_trop)
        TNS220prior = (TNS220tonorm-self.inp_subTNS220[self.TBP_idx])/self.inp_divTNS220[self.TBP_idx]

        post = np.concatenate([X[:,:30],TNS220prior.astype(np.float32),X[:,60:]], axis=1)

        X_result = post
        return X_result    

    
class SHF2SHF_nsDELTNumpy:
    def __init__(self, inp_sub, inp_div, inp_subSHF, inp_divSHF, hyam, hybm, epsilon):
        self.inp_sub, self.inp_div, inp_subSHF, inp_divSHF, self.hyam, self.hybm, self.epsilon = \
        np.array(inp_sub), np.array(inp_div), \
        np.array(inp_subSHF), np.array(inp_divSHF), \
        np.array(hyam), np.array(hybm),np.array(epsilon)
        
        # Define variable indices here
        # Input
        self.QBP_idx = slice(0,30)
        self.TBP_idx = slice(30,60)
        self.PS_idx = 60
        self.SHFLX_idx = 62
        self.LHFLX_idx = 63
        
    def process(self,X):
        Tprior = X[:,self.TBP_idx]*self.inp_div[self.TBP_idx]+self.inp_sub[self.TBP_idx]
        SHFprior = X[:,self.SHFLX_idx]*self.inp_div[self.SHFLX_idx]+self.inp_sub[self.SHFLX_idx]
        
        #Tile_dim = [1,30]
        #TSprior = np.tile(np.expand_dims(Tprior[:,-1],axis=1),Tile_dim)
        Tdenprior = np.maximum(self.epsilon,TSprior-Tprior[:,-1])
        
        #SHFtile = np.tile(np.expand_dims(SHFprior,axis=1),Tile_dim)
        SHFscaled = (SHFprior/(C_P*Tdenprior)-\
                     self.inp_subT[self.TBP_idx])/self.inp_divT[self.TBP_idx]
        Tile_dim = [1,1]
        SHFtile = np.tile(np.expand_dims(SHFscaled.astype(np.float32),axis=1),Tile_dim)
        
        
        post = np.concatenate([X[:,:self.SHFLX_idx],SHFtile,X[:,self.LHFLX_idx:]], axis=1)
        
        X_result = post
        return post 

class LHF2LHF_nsDELQNumpy:
    def __init__(self, inp_sub, inp_div, inp_subLHF, inp_divLHF, hyam, hybm, epsilon):
        self.inp_sub, self.inp_div, self.inp_subLHF, self.inp_divLHF, self.hyam, self.hybm, self.epsilon = \
        np.array(inp_sub), np.array(inp_div), \
        np.array(inp_subLHF), np.array(inp_divLHF), \
        np.array(hyam), np.array(hybm),np.array(epsilon)
        
        # Define variable indices here
        # Input
        self.QBP_idx = slice(0,30)
        self.TBP_idx = slice(30,60)
        self.PS_idx = 60
        self.SHFLX_idx = 62
        self.LHFLX_idx = 63
        
    def process(self,X):
        qvprior = X[:,self.QBP_idx]*self.inp_div[self.QBP_idx]+self.inp_sub[self.QBP_idx]
        Tprior = X[:,self.TBP_idx]*self.inp_div[self.TBP_idx]+self.inp_sub[self.TBP_idx]
        PSprior = X[:,self.PS_idx]*self.inp_div[self.PS_idx]+self.inp_sub[self.PS_idx]
        LHFprior = X[:,self.LHFLX_idx]*self.inp_div[self.LHFLX_idx]+self.inp_sub[self.LHFLX_idx]
        
        Qdenprior = (ThermLibNumpy.qsatNumpy(Tprior,P0,PSprior,self.hyam,self.hybm))[:,-1]-qvprior[:,-1]
        Qdenprior = np.maximum(self.epsilon,Qdenprior)
        
        Tile_dim = [1,1]
        #LHFtile = np.tile(np.expand_dims(LHFprior,axis=1),Tile_dim)
        LHFscaled = (LHFprior/(L_V*Qdenprior)-\
                     self.inp_subLHF[self.LHFLX_idx])/self.inp_divLHF[self.LHFLX_idx]
        LHFtile = np.tile(np.expand_dims(LHFscaled.astype(np.float32),axis=1),Tile_dim)
        
        post = np.concatenate([X[:,:self.LHFLX_idx],LHFtile,\
                               X[:,(self.LHFLX_idx+1):]],axis=1)
        
        X_result = post
        return post
    
class LHF2LHF_nsQNumpy:
    def __init__(self, inp_sub, inp_div, inp_subLHF, inp_divLHF, hyam, hybm, epsilon):
        self.inp_sub, self.inp_div, self.inp_subLHF, self.inp_divLHF, self.hyam, self.hybm, self.epsilon = \
        np.array(inp_sub), np.array(inp_div), \
        np.array(inp_subLHF), np.array(inp_divLHF), \
        np.array(hyam), np.array(hybm),np.array(epsilon)
        
        # Define variable indices here
        # Input
        self.QBP_idx = slice(0,30)
        self.TBP_idx = slice(30,60)
        self.PS_idx = 60
        self.SHFLX_idx = 62
        self.LHFLX_idx = 63
        
    def process(self,X):
        qvprior = X[:,self.QBP_idx]*self.inp_div[self.QBP_idx]+self.inp_sub[self.QBP_idx]
        LHFprior = X[:,self.LHFLX_idx]*self.inp_div[self.LHFLX_idx]+self.inp_sub[self.LHFLX_idx]
        
        Qdenprior = np.maximum(self.epsilon,qvprior[:,-1])
        
        #Tile_dim = [1,30]
        #LHFtile = np.tile(np.expand_dims(LHFprior,axis=1),Tile_dim)
        LHFscaled = (LHFprior/(L_V*Qdenprior)-\
                     self.inp_subLHF[self.LHFLX_idx])/self.inp_divLHF[self.LHFLX_idx]
        
        Tile_dim = [1,1]
        LHFtile = np.tile(np.expand_dims(LHFscaled.astype(np.float32),axis=1),Tile_dim)
        post = np.concatenate([X[:,:self.LHFLX_idx],LHFtile,\
                               X[:,(self.LHFLX_idx+1):]],axis=1)
        
        X_result = post
        return post

class LhflxTransNumpy:
    def __init__(self, inp_sub, inp_div, hyam, hybm,epsilon=1e-3):
        self.inp_sub, self.inp_div, self.hyam, self.hybm = \
            np.array(inp_sub), np.array(inp_div),\
        np.array(hyam), np.array(hybm)
        # Define variable indices here
        # Input
        self.QBP_idx = slice(0,30)
        self.epsilon = epsilon
        self.TBP_idx = slice(30,60)
        self.PS_idx = 60
        self.SHFLX_idx = 62
        self.LHFLX_idx = 63
        self.TS_idx = 64
        
    def process(self,X):
        qvprior = X[:,self.QBP_idx]*self.inp_div[self.QBP_idx]+self.inp_sub[self.QBP_idx]
        X[:,self.LHFLX_idx] = X[:,self.LHFLX_idx]/(L_V*(self.epsilon+qvprior[:,-1]))
        return X

    def process_V1(self,X):
        Tprior = X[:,self.TBP_idx]*self.inp_div[self.TBP_idx]+self.inp_sub[self.TBP_idx]
        qvprior = X[:,self.QBP_idx]*self.inp_div[self.QBP_idx]+self.inp_sub[self.QBP_idx]
        PSprior = X[:,self.PS_idx]*self.inp_div[self.PS_idx]+self.inp_sub[self.PS_idx]
        qsat = ThermLibNumpy.qsatNumpy(Tprior,1e5,PSprior,self.hyam,self.hybm)
        X[:,self.LHFLX_idx] = X[:,self.LHFLX_idx]/(L_V*qsat[:,-1])

        return X





################################### Scaling layer Numpy #################################################
'''appends the scaling factor to the input array'''
'''takes non normalized inputs '''
class ScalingNumpy:
    def __init__(self,hyam,hybm):
        self.hyam = hyam
        self.hybm = hybm

    def __crhScaling(self,inp):
        qv0 = inp[:,:30]
        T = inp[:,30:60]
        ps = inp[:,60]
        dP0 = CrhClass().dP(ps)
        qsat0 = CrhClass().qsat(T,P0,ps,self.hyam,self.hybm)
        return np.sum(qv0*dP0,axis=1)/np.sum(qsat0*dP0,axis=1)

    def __pwScaling(self,inp):
        qv0 = inp[:,:30]
        T = inp[:,30:60]
        ps = inp[:,60]
        dP0 = ThermLibNumpy.dPNumpy(ps)
        return np.sum(qv0*dP0/G,axis=1)

    def process(self,X):
        scalings = self.__pwScaling(X).reshape(-1,1)
        return scalings

    def crh(self,X):
        return self.__crhScaling(X)


################################### Level Transformation layer Numpy #################################################

'''this is the forward interpolation layer lev-levTilde takes the normalized input vectors'''

class InterpolationNumpy:
    def __init__(self,lev,is_continous,Tnot,lower_lim,interm_size):
        self.lev = lev
        self.lower_lim = lower_lim
        self.Tnot = Tnot
        self.is_continous = is_continous ## for discrete or continous transformation
        self.interm_size = interm_size

    @staticmethod
    def levTildeDiscrete(X,lev,inp_sub, inp_div, batch_size=1024,interm_dim_size=40):
        '''can be used independently
            note: the input X should be raw transformed i.e without any other transformation(RH or QV)
            or if given in that way then please provide appropriate inp_sub, inp_div
        ''' ## not being used in the process method
        X_denormalized = X*inp_div+inp_sub
        X_pressure = X[:,:30]
        X_temperature = X[:,30:60] #batchx30
        X_temperature_denomalized = X_denormalized[:,30:60]

        lev_stacked = np.repeat(np.array(lev).reshape(1,-1),batch_size,axis=0)
        imin = np.argmin(X_temperature_denomalized[:,6:],axis=1)+6
        lev_roof = np.array(lev[imin])
        lev_tilde = (lev_stacked[:,-1].reshape(-1,1)-lev_stacked[:])/(lev_stacked[:,-1].reshape(-1,1)-lev_roof.reshape(-1,1))#batchx30


        lev_tilde_after_single = np.linspace(1.4,0,num=interm_dim_size)

        X_temperature_after = []
        X_pressure_after = []

        for i in range(batch_size):
            X_temperature_after.append(np.interp(lev_tilde_after_single, np.flip(lev_tilde[i]), np.flip(X_temperature[i])))
            X_pressure_after.append(np.interp(lev_tilde_after_single, np.flip(lev_tilde[i]), np.flip(X_pressure[i])))

        X_temperature_after = np.array(X_temperature_after)
        X_pressure_after = np.array(X_pressure_after)

        X_result = np.hstack((X_pressure_after,X_temperature_after))
        X_result = np.hstack((X_result,X[:,60:64]))

        return  X_result, lev_tilde, lev_roof

    @staticmethod
    def levTildeConti(X,lev,inp_sub,inp_div,batch_size=1024,interm_dim_size=40,Tnot=5):
        '''can be used independently
            note: the input X should be raw transformed i.e without any other transformation(RH or QV)
            or if given in that way then please provide appropriate inp_sub, inp_div
        ''' ## not being used in the process method
        X_denormalized = X*inp_div+inp_sub
        X_pressure = X[:,:30]
        X_temperature = X[:,30:60] #batchx30
        X_temperature_denormalized = X_denormalized[:,30:60]
        lev_stacked = np.repeat(np.array(lev).reshape(1,-1),batch_size,axis=0)
        imin = np.argmin(X_temperature_denormalized[:,6:],axis=1)+6 #take one below this and the next one
        lev1 = np.array(lev[imin-1]) #batch_size dim
        lev2 = np.array(lev[imin+1])
        T1 = np.take_along_axis( X_temperature_denormalized, (imin-1).reshape(-1,1),axis=1).flatten() ## batch_size
        T2 = np.take_along_axis( X_temperature_denormalized, (imin+1).reshape(-1,1),axis=1).flatten() ## batch_size
        deltaT = abs(T2-T1)
        alpha = (1.0/2)*(2 - np.exp(-1*deltaT/Tnot))
        lev_roof = alpha*lev1 + (1-alpha)*lev2

        lev_tilde = (lev_stacked[:,-1].reshape(-1,1)-lev_stacked[:])/(lev_stacked[:,-1].reshape(-1,1)-lev_roof.reshape(-1,1))#batchx30
        lev_tilde_after_single = np.linspace(1.4,0,num=interm_dim_size)

        X_temperature_after = []
        X_pressure_after = []

        for i in range(batch_size):
            X_temperature_after.append(np.interp(lev_tilde_after_single, np.flip(lev_tilde[i]), np.flip(X_temperature[i])))
            X_pressure_after.append(np.interp(lev_tilde_after_single, np.flip(lev_tilde[i]), np.flip(X_pressure[i])))

        X_temperature_after = np.array(X_temperature_after)
        X_pressure_after = np.array(X_pressure_after)

        X_result = np.hstack((X_pressure_after,X_temperature_after))
        X_result = np.hstack((X_result,X[:,60:64]))

        return  X_result, lev_tilde, lev_roof


    def process(self,X,X_result):

        batch_size = X.shape[0]
        X_temperature = X[:,30:60]
        lev_stacked = np.repeat(np.array(self.lev).reshape(1,-1),batch_size,axis=0)
        imin = np.argmin(X_temperature[:,self.lower_lim:],axis=1)+self.lower_lim
        if self.is_continous:
            lower = np.clip(imin-1,0,None)
            upper = np.clip(imin+1,None,29)
            lev1 = np.array(self.lev[lower]) #batch_size dim
            lev2 = np.array(self.lev[upper])
            T1 = np.take_along_axis( X_temperature, (lower).reshape(-1,1),axis=1).flatten() ## batch_size
            T2 = np.take_along_axis( X_temperature, (upper).reshape(-1,1),axis=1).flatten() ## batch_size
            deltaT = abs(T2-T1)
            alpha = (1.0/2)*(2 - np.exp(-1*deltaT/self.Tnot))
            lev_roof = alpha*lev1 + (1-alpha)*lev2
        else:
            lev_roof = np.array(self.lev[imin])

        lev_tilde = (lev_stacked[:,-1].reshape(-1,1)-lev_stacked[:])/(lev_stacked[:,-1].reshape(-1,1)-lev_roof.reshape(-1,1))


        ## lef tilde after
        X_temperature = X_result[:,30:60] #batchx30
        X_pressure = X_result[:,:30]
        lev_tilde_after_single = np.linspace(1.4,0,num=self.interm_size)
        X_temperature_after = []
        X_pressure_after = []

        for i in range(batch_size):
            X_temperature_after.append(np.interp(lev_tilde_after_single, np.flip(lev_tilde[i]), np.flip(X_temperature[i])))
            X_pressure_after.append(np.interp(lev_tilde_after_single, np.flip(lev_tilde[i]), np.flip(X_pressure[i])))

        X_temperature_after = np.array(X_temperature_after)
        X_pressure_after = np.array(X_pressure_after)
        X_processed = np.hstack((X_pressure_after,X_temperature_after,X_result[:,60:64],lev_tilde))

        return X_processed

#################################################################################################################
class DataGeneratorCI(DataGenerator):
    def __init__(self, data_fn, input_vars, output_vars,
             norm_fn=None, input_transform=None, output_transform=None,
             batch_size=1024, shuffle=True, xarray=False, var_cut_off=None, 
             Qscaling=None,
             Tscaling=None,
             LHFscaling=None,
             SHFscaling=None,
             output_scaling=False,
             interpolate=False,
             hyam=None,hybm=None,
             inp_sub_Qscaling=None,inp_div_Qscaling=None,
             inp_sub_Tscaling=None,inp_div_Tscaling=None,
             inp_sub_LHFscaling=None,inp_div_LHFscaling=None,
             inp_sub_SHFscaling=None,inp_div_SHFscaling=None,
             lev=None, interm_size=40,
             lower_lim=6,
             is_continous=True,Tnot=5,epsQ=1e-3,epsT=1,
                 mode='train'):
        self.output_scaling = output_scaling
        self.interpolate = interpolate
        self.Qscaling = Qscaling
        self.Tscaling = Tscaling
        self.LHFscaling = LHFscaling
        self.SHFscaling = SHFscaling
        self.inp_shape = 64
        self.mode=mode
        super().__init__(data_fn, input_vars,output_vars,norm_fn,input_transform,output_transform,
                        batch_size,shuffle,xarray,var_cut_off) ## call the base data generator
        self.inp_sub = self.input_transform.sub
        self.inp_div = self.input_transform.div
        if Qscaling=='RH':
            self.QLayer = QV2RHNumpy(self.inp_sub,self.inp_div,inp_sub_Qscaling,inp_div_Qscaling,hyam,hybm)
        elif Qscaling=='QSATdeficit':
            self.QLayer = QV2QSATdeficitNumpy(self.inp_sub,self.inp_div,inp_sub_Qscaling,inp_div_Qscaling,hyam,hybm)
        if Tscaling=='TfromNS':
            self.TLayer = T2TmTNSNumpy(self.inp_sub,self.inp_div,inp_sub_Tscaling,inp_div_Tscaling,hyam,hybm)
        elif Tscaling=='BCONS':
            self.TLayer = T2BCONSNumpy(self.inp_sub,self.inp_div,inp_sub_Tscaling,inp_div_Tscaling,hyam,hybm)
        elif Tscaling=='BMSE':
            self.TLayer = T2BMSENumpy(self.inp_sub,self.inp_div,inp_sub_Tscaling,inp_div_Tscaling,hyam,hybm)
        elif Tscaling=='T_NSto220':
            self.TLayer = T2T_NSto220Numpy(self.inp_sub,self.inp_div,inp_sub_Tscaling,inp_div_Tscaling,hyam,hybm)
        if LHFscaling=='LHF_nsDELQ':
            self.LHFLayer = LHF2LHF_nsDELQNumpy(self.inp_sub,self.inp_div,inp_sub_LHFscaling,inp_div_LHFscaling,hyam,hybm,epsQ)
        elif LHFscaling=='LHF_nsQ':
            self.LHFLayer = LHF2LHF_nsQNumpy(self.inp_sub,self.inp_div,inp_sub_LHFscaling,inp_div_LHFscaling,hyam,hybm,epsQ)
        if SHFscaling=='SHF_nsDELT':
            self.SHFLayer = SHF2SHF_nsDELTNumpy(self.inp_sub,self.inp_div,inp_sub_SHFscaling,inp_div_SHFscaling,hyam,hybm,epsT)
        if output_scaling:
            self.scalingLayer = ScalingNumpy(hyam,hybm)
            self.inp_shape += 1
        if interpolate:
            self.interpLayer = InterpolationNumpy(lev,is_continous,Tnot,lower_lim,interm_size)
            self.inp_shape += interm_size*2 + 4 + 30 ## 4 same as 60-64 and 30 for lev_tilde.size
    def __getitem__(self, index):
        # Compute start and end indices for batch
        start_idx = index * self.batch_size
        end_idx = start_idx + self.batch_size
        # Grab batch from data
        batch = self.data_ds['vars'][start_idx:end_idx]
        # Split into inputs and outputs
        X = batch[:, self.input_idxs]
        Y = batch[:, self.output_idxs]
        # Normalize
        X_norm = self.input_transform.transform(X)
        Y = self.output_transform.transform(Y)
        X_result = np.copy(X_norm)
        if self.Qscaling:
            X_result = self.QLayer.process(X_result)
        if self.Tscaling:
            # tgb - 3/21/2021 - BCONS needs qv in kg/kg as an input
            if self.Tscaling=='BCONS' or self.Tscaling=='BMSE':
                if self.Qscaling:
                    X_resultT = self.TLayer.process(X_norm)
                    X_result = np.concatenate([X_result[:,:30],X_resultT[:,30:60],X_result[:,60:]], axis=1)
                else:
                    X_result = self.TLayer.process(X_result)
            else:
                X_result = self.TLayer.process(X_result)
        if self.SHFscaling:
            X_result = self.SHFLayer.process(X_result)
        if self.LHFscaling:
            # tgb - 3/22/2021 - LHF_ns(DEL)Q needs qv in kg/kg and T in K
            if self.Qscaling or self.Tscaling:
                X_resultLHF = self.LHFLayer.process(X_norm)
                X_result = np.concatenate([X_result[:,:60],X_resultLHF[:,60:]],axis=1)
            else:
                X_result = self.LHFLayer.process(X_result)
        if self.output_scaling:
            scalings = self.scalingLayer.process(X)
            X_result = np.hstack((X_result,scalings))
        if self.interpolate:
            interpolated = self.interpLayer.process(X,X_result)
            X_result = np.hstack((X_result,interpolated))
        if self.mode=='val':
            return xr.DataArray(X_result), xr.DataArray(Y)
        return X_result,Y
    ##transforms the input data into the required format, take the unnormalized dataset
    def transform(self,X):
        X_norm = self.input_transform.transform(X)
        X_result = X_norm
        if self.Qscaling:
            X_result = self.QLayer.process(X_result)
        if self.Tscaling:
            X_result = self.TLayer.process(X_result)
        if self.SHFscaling:
            X_result = self.SHFLayer.process(X_result)
        if self.LHFscaling:
            X_result = self.LHFLayer.process(X_result)
        if self.scaling:
            scalings = self.scalingLayer.process(X)
            X_result = np.hstack((X_result,scalings))
        if self.interpolate:
            interpolated = self.interpLayer.process(X,X_result)
            X_result = np.hstack((X_result,interpolated))
        return X_result
######################            Class for model diagnostics      #################
class ClimateNet:
    def __init__(self,dict_lay,data_fn,config_fn,
             lev,hyam,hybm,TRAINDIR,
             nlat, nlon, nlev, ntime,
             inp_subRH,inp_divRH,
             inp_subTNS,inp_divTNS,
             rh_trans=False,t2tns_trans=False,
             lhflx_trans=False,
             scaling=False,interpolate=False,
             model=None,
             pos_model=None,neg_model=None,
             #this can be none if no scaling is present
             train_gen_RH_pos=None,train_gen_RH_neg=None,
             train_gen_TNS_pos=None,train_gen_TNS_neg=None,
                 exp = None
                ):


        with open(config_fn, 'r') as f:
            config = yaml.load(f)
        out_scale_dict = load_pickle(config['output_dict'])
        ngeo = nlat * nlon
        in_vars = config['inputs']
        out_vars = config['outputs']

        self.valid_gen = DataGeneratorClimInv(
                data_fn = data_fn,
                input_vars=in_vars,
                output_vars=out_vars,
                norm_fn=config['data_dir'] + config['norm_fn'],
                input_transform=(config['input_sub'], config['input_div']),
                output_transform=out_scale_dict,
                batch_size=ngeo,
                shuffle=False,
                xarray=True,
                var_cut_off=config['var_cut_off'] if 'var_cut_off' in config.keys() else None,
                rh_trans = rh_trans,t2tns_trans = t2tns_trans,
                lhflx_trans = lhflx_trans,
                scaling = scaling,
                lev=lev,interpolate = interpolate,
                hyam=hyam,hybm=hybm,
                inp_subRH=inp_subRH, inp_divRH=inp_divRH,
                inp_subTNS=inp_subTNS,inp_divTNS=inp_divTNS,
                mode='val',
                exp = exp

        )

        self.rh_trans = rh_trans
        self.t2tns_trans = t2tns_trans
        self.lhflx_trans = lhflx_trans
        self.scaling = scaling
        self.interpolate = interpolate
        self.subQ,self.divQ = np.array(self.valid_gen.input_transform.sub),np.array(self.valid_gen.input_transform.div)

        if model != None:
            self.model = load_model(model,custom_objects=dict_lay)

        if scaling:
            self.pos_model = load_model(pos_model,custom_objects=dict_lay)
            self.neg_model = load_model(neg_model,custom_objects=dict_lay)

            #just for the norm values
            self.pos_data_gen = DataGeneratorClimInv(
                                data_fn = TRAINDIR+'PosCRH_CI_SP_M4K_train_shuffle.nc',
                                input_vars = in_vars,
                                output_vars = out_vars,
                                norm_fn = TRAINDIR+'PosCRH_CI_SP_M4K_NORM_norm.nc',
                                input_transform = ('mean', 'maxrs'),
                                output_transform = out_scale_dict,
                                batch_size=1024,
                                shuffle=True,
                                lev=lev,
                                hyam=hyam,hybm=hybm,
                                inp_subRH=train_gen_RH_pos.input_transform.sub, inp_divRH=train_gen_RH_pos.input_transform.div,
                                inp_subTNS=train_gen_TNS_pos.input_transform.sub,inp_divTNS=train_gen_TNS_pos.input_transform.div,
                                is_continous=True,
                                scaling=True,
                                interpolate=interpolate,
                                rh_trans=rh_trans,
                                t2tns_trans=t2tns_trans,
                                lhflx_trans=lhflx_trans
                            )

            self.neg_data_gen = DataGeneratorClimInv(
                                data_fn = TRAINDIR+'NegCRH_CI_SP_M4K_train_shuffle.nc',
                                input_vars = in_vars,
                                output_vars = out_vars,
                                norm_fn = TRAINDIR+'NegCRH_CI_SP_M4K_NORM_norm.nc',
                                input_transform = ('mean', 'maxrs'),
                                output_transform = out_scale_dict,
                                batch_size=1024,
                                shuffle=True,
                                lev=lev,
                                hyam=hyam,hybm=hybm,
                                inp_subRH=train_gen_RH_neg.input_transform.sub, inp_divRH=train_gen_RH_neg.input_transform.div,
                                inp_subTNS=train_gen_TNS_neg.input_transform.sub,inp_divTNS=train_gen_TNS_neg.input_transform.div,
                                is_continous=True,
                                interpolate=interpolate,
                                scaling=False,
                                rh_trans=rh_trans,
                                t2tns_trans=t2tns_trans,
                                lhflx_trans=lhflx_trans
                            )


    def reorder(self,op_pos,op_neg,mask):
        op = []
        pos_i=0
        neg_i = 0
        for m in mask:
            if m:
                op.append(op_pos[pos_i])
                pos_i += 1
            else:
                op.append(op_neg[neg_i])
                neg_i += 1
        return np.array(op)


    def predict_on_batch(self,inp):
        #inp = batch x 179
        inp_de = inp*self.divQ+self.subQ
        if not self.scaling:
            inp_pred = self.valid_gen.transform(inp_de)
            return self.model.predict_on_batch(inp_pred)

        mask = ScalingNumpy(hyam,hybm).crh(inp_de)> 0.8
        pos_inp = inp[mask]
        neg_inp = inp[np.logical_not(mask)]
        ### for positive
        pos_inp = pos_inp*self.divQ + self.subQ
        pos_inp = self.pos_data_gen.transform(pos_inp)
        op_pos = self.pos_model.predict_on_batch(pos_inp)
        neg_inp = neg_inp*self.divQ + self.subQ
        neg_inp = self.neg_data_gen.transform(neg_inp)
        op_neg = self.neg_model.predict_on_batch(neg_inp)
        op = self.reorder(np.array(op_pos),np.array(op_neg),mask)
        return op

    ##just for network is scaling is present
    def predict_on_batch_seperate(self,inp):
        if self.scaling==False:
            raise("Scaling is not present in this model")

        inp_de = inp*self.divQ + self.subQ
        mask = ScalingNumpy(hyam,hybm).crh(inp_de)> 0.8
        pos_inp = inp[mask]
        neg_inp = inp[np.logical_not(mask)]

        pos_inp = pos_inp*self.divQ + self.subQ
        pos_inp = self.pos_data_gen.transform(pos_inp)
        neg_inp = neg_inp*self.divQ + self.subQ
        neg_inp = self.neg_data_gen.transform(neg_inp)

        op_pos = self.pos_model.predict_on_batch(pos_inp)
        op_neg = self.neg_model.predict_on_batch(neg_inp)

        return mask,op_pos,op_neg


def load_climate_model(dict_lay,config_fn,data_fn,lev,hyam,hybm,TRAINDIR,
                       inp_subRH,inp_divRH,
                       inp_subTNS,inp_divTNS,
                       nlat=64, nlon=128, nlev=30, ntime=48,
                        rh_trans=False,t2tns_trans=False,
                        lhflx_trans=False,
                        scaling=False,interpolate=False,
                        model=None,
                        pos_model=None,neg_model=None,
                        train_gen_RH_pos=None,train_gen_RH_neg=None,
                        train_gen_TNS_pos=None,train_gen_TNS_neg=None,exp=None):

    obj = ClimateNet(dict_lay,data_fn,config_fn,
                     lev,hyam,hybm,TRAINDIR,
                     nlat, nlon, nlev, ntime,
                     inp_subRH,inp_divRH,
                     inp_subTNS,inp_divTNS,
                    rh_trans=rh_trans,t2tns_trans=t2tns_trans,
                    lhflx_trans=lhflx_trans, scaling=scaling,
                    interpolate=interpolate,
                    model = model,
                    pos_model=pos_model,neg_model=neg_model,
                    train_gen_RH_pos=train_gen_RH_pos,train_gen_RH_neg=train_gen_RH_neg,
                    train_gen_TNS_pos=train_gen_TNS_pos,train_gen_TNS_neg=train_gen_TNS_neg,exp=exp)
    return obj
