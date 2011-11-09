__authors__ = "Ian Goodfellow"
__copyright__ = "Copyright 2011, Universite de Montreal"
__credits__ = ["Ian Goodfellow"]
__license__ = "3-clause BSD"
__maintainer__ = "Ian Goodfellow"


import time
from pylearn2.models.model import Model
from theano import config, function, shared
import theano.tensor as T
import numpy as np
import warnings
from theano.gof.op import get_debug_values, debug_error_message
from pylearn2.utils import make_name, as_floatX

warnings.warn('pddbm changing the recursion limit')
import sys
sys.setrecursionlimit(50000)

def numpy_norms(W):
    """ returns a vector containing the L2 norm of each
    column of W, where W and the return value are
    numpy ndarrays """
    return np.sqrt(1e-8+np.square(W).sum(axis=0))

def theano_norms(W):
    """ returns a vector containing the L2 norm of each
    column of W, where W and the return value are symbolic
    theano variables """
    return T.sqrt(as_floatX(1e-8)+T.sqr(W).sum(axis=0))

def rotate_towards(old_W, new_W, new_coeff):
    """
        old_W: every column is a unit vector

        for each column, rotates old_w toward
            new_w by new_coeff * theta where
            theta is the angle between them
    """

    norms = theano_norms(new_W)

    #update, scaled back onto unit sphere
    scal_points = new_W / norms.dimshuffle('x',0)

    #dot product between scaled update and current W
    dot_update = (old_W * scal_points).sum(axis=0)

    theta = T.arccos(dot_update)

    rot_amt = new_coeff * theta

    new_basis_dir = scal_points - dot_update * old_W

    new_basis_norms = theano_norms(new_basis_dir)

    new_basis = new_basis_dir / new_basis_norms

    rval = T.cos(rot_amt) * old_W + T.sin(rot_amt) * new_basis

    return rval

def full_min(var):
    """ returns a symbolic expression for the value of the minimal
    element of symbolic tensor. T.min does something else as of
    the time of this writing. """
    return var.min(axis=range(0,len(var.type.broadcastable)))

def full_max(var):
    """ returns a symbolic expression for the value of the maximal
        element of a symbolic tensor. T.max does something else as of the
        time of this writing. """
    return var.max(axis=range(0,len(var.type.broadcastable)))

class SufficientStatistics:
    """ The SufficientStatistics class computes several sufficient
        statistics of a minibatch of examples / variational parameters.
        This is mostly for convenience since several expressions are
        easy to express in terms of these same sufficient statistics.
        Also, re-using the same expression for the sufficient statistics
        in multiple code locations can reduce theano compilation time.
        The current version of the S3C code no longer supports features
        like decaying sufficient statistics since these were not found
        to be particularly beneficial relative to the burden of computing
        the O(nhid^2) second moment matrix. The current version of the code
        merely computes the sufficient statistics apart from the second
        moment matrix as a notational convenience. Expressions that most
        naturally are expressed in terms of the second moment matrix
        are now written with a different order of operations that
        avoids O(nhid^2) operations but whose dependence on the dataset
        cannot be expressed in terms only of sufficient statistics."""


    def __init__(self, d):
        self. d = {}
        for key in d:
            self.d[key] = d[key]

    @classmethod
    def from_observations(self, needed_stats, V, H_hat, S_hat, var_s0_hat, var_s1_hat):
        """
            returns a SufficientStatistics

            needed_stats: a set of string names of the statistics to include

            V: a num_examples x nvis matrix of input examples
            H_hat: a num_examples x nhid matrix of \hat{h} variational parameters
            S_hat: variational parameters for expectation of s given h=1
            var_s0_hat: variational parameters for variance of s given h=0
                        (only a vector of length nhid, since this is the same for
                        all inputs)
            var_s1_hat: variational parameters for variance of s given h=1
                        (again, a vector of length nhid)
        """

        m = T.cast(V.shape[0],config.floatX)

        H_name = make_name(H_hat, 'anon_H_hat')
        Mu1_name = make_name(S_hat, 'anon_S_hat')

        #mean_h
        assert H_hat.dtype == config.floatX
        mean_h = T.mean(H_hat, axis=0)
        assert H_hat.dtype == mean_h.dtype
        assert mean_h.dtype == config.floatX
        mean_h.name = 'mean_h('+H_name+')'

        #mean_v
        mean_v = T.mean(V,axis=0)

        #mean_sq_v
        mean_sq_v = T.mean(T.sqr(V),axis=0)

        #mean_s1
        mean_s1 = T.mean(S_hat,axis=0)

        #mean_sq_s
        mean_sq_S = H_hat * (var_s1_hat + T.sqr(S_hat)) + (1. - H_hat)*(var_s0_hat)
        mean_sq_s = T.mean(mean_sq_S,axis=0)

        #mean_hs
        mean_HS = H_hat * S_hat
        mean_hs = T.mean(mean_HS,axis=0)
        mean_hs.name = 'mean_hs(%s,%s)' % (H_name, Mu1_name)
        mean_s = mean_hs #this here refers to the expectation of the s variable, not s_hat
        mean_D_sq_mean_Q_hs = T.mean(T.sqr(mean_HS), axis=0)

        #mean_sq_hs
        mean_sq_HS = H_hat * (var_s1_hat + T.sqr(S_hat))
        mean_sq_hs = T.mean(mean_sq_HS, axis=0)
        mean_sq_hs.name = 'mean_sq_hs(%s,%s)' % (H_name, Mu1_name)

        #mean_sq_mean_hs
        mean_sq_mean_hs = T.mean(T.sqr(mean_HS), axis=0)
        mean_sq_mean_hs.name = 'mean_sq_mean_hs(%s,%s)' % (H_name, Mu1_name)

        #mean_hsv
        sum_hsv = T.dot(mean_HS.T,V)
        sum_hsv.name = 'sum_hsv<from_observations>'
        mean_hsv = sum_hsv / m


        d = {
                    "mean_h"                :   mean_h,
                    "mean_v"                :   mean_v,
                    "mean_sq_v"             :   mean_sq_v,
                    "mean_s"                :   mean_s,
                    "mean_s1"               :   mean_s1,
                    "mean_sq_s"             :   mean_sq_s,
                    "mean_hs"               :   mean_hs,
                    "mean_sq_hs"            :   mean_sq_hs,
                    "mean_sq_mean_hs"       :   mean_sq_mean_hs,
                    "mean_hsv"              :   mean_hsv,
                }


        final_d = {}

        for stat in needed_stats:
            final_d[stat] = d[stat]
            final_d[stat].name = 'observed_'+stat

        return SufficientStatistics(final_d)


class PDDBM(Model):

    def __init__(self,
            s3c,
            dbm,
            inference_procedure,
            print_interval = 10000):
        """
            s3c: a galatea.s3c.s3c.S3C object
                will become owned by the PDDBM
                it won't be deleted but many of its fields will change
            dbm: a pylearn2.dbm.DBM object
                will become owned by the PDDBM
                it won't be deleted but many of its fileds will change
            inference_procedure: a galatea.pddbm.pddbm.InferenceProcedure
            print_interval: number of examples between each status printout
        """

        super(PDDBM,self).__init__()

        self.s3c = s3c
        s3c.m_step = None
        self.dbm = dbm

        self.nvis = s3c.nvis

        #don't support some exotic options on s3c
        for option in ['monitor_functional',
                       'recycle_q',
                       'debug_m_step']:
            if getattr(s3c, option):
                warnings.warn('PDDBM does not support '+option+' in '
                        'the S3C layer, disabling it')
                setattr(s3c, option, False)

        self.print_interval = print_interval

        s3c.print_interval = None
        dbm.print_interval = None

        self.redo_everything()


    def set_dtype(self, dtype):
        for field in dir(self):
            obj = getattr(self, field)
            if hasattr(obj, 'get_value'):
                setattr(self, field, shared(np.cast[dtype](obj.get_value())))
            if hasattr(obj, 'set_dtype'):
                obj.set_dtype(dtype)


    def redo_everything(self):

        self.dbm.redo_everything()
        self.s3c.redo_everything()

        self.test_batch_size = 2

        self.redo_theano()


    def get_monitoring_channels(self, V):
            try:
                self.compile_mode()

                self.s3c.set_monitoring_channel_prefix('s3c_')

                rval = self.s3c.get_monitoring_channels(V, self)

                from_inference_procedure = self.inference_procedure.get_monitoring_channels(V, self)

                rval.update(from_inference_procedure)

                self.dbm.set_monitoring_channel_prefix('dbm_')

                from_dbm = self.dbm.get_monitoring_channels(V, self)

                rval.update(from_dbm)

            finally:
                self.deploy_mode()

    def compile_mode(self):
        """ If any shared variables need to have batch-size dependent sizes,
        sets them all to the sizes used for interactive debugging during graph construction """
        pass

    def deploy_mode(self):
        """ If any shared variables need to have batch-size dependent sizes, sets them all to their runtime sizes """
        pass

    def get_params(self):
        return list(set(self.s3c.get_params()).union(set(self.dbm.get_params)))

    def make_learn_func(self, V):
        """
        V: a symbolic design matrix
        """

        raise NotImplementedError("This is mostly just a copy-paste of S3C, hasn't been rewritten for PDDBM yet")

        hidden_obs = self.inference_procedure.infer(V)

        stats = SufficientStatistics.from_observations(needed_stats = self.m_step.needed_stats(),
                V = V, **hidden_obs)

        H_hat = hidden_obs['H_hat']
        S_hat = hidden_obs['S_hat']

        learning_updates = self.m_step.get_updates(self, stats, H_hat, S_hat)

        if self.recycle_q:
            learning_updates[self.prev_H] = H_hat
            learning_updates[self.prev_Mu1] = S_hat

        self.censor_updates(learning_updates)


        print "compiling function..."
        t1 = time.time()
        rval = function([V], updates = learning_updates)
        t2 = time.time()
        print "... compilation took "+str(t2-t1)+" seconds"
        print "graph size: ",len(rval.maker.env.toposort())

        return rval

    def censor_updates(self, updates):

        self.s3c.censor_updates(updates)
        self.dbm.censor_update(updates)

    def random_design_matrix(self, batch_size, theano_rng):

        if not hasattr(self,'p'):
            self.make_pseudoparams()

        H_sample = self.dbm.random_design_matrix(batch_size, theano_rng)

        V_sample = self.s3c.random_design_matrix(batch_size, theano_rng, H_sample = H_sample)

        return V_sample



    def redo_theano(self):
        try:
            self.compile_mode()

            init_names = dir(self)

            self.make_pseudoparams()

            X = T.matrix(name='V')
            X.tag.test_value = np.cast[config.floatX](self.rng.randn(self.test_batch_size,self.nvis))

            self.learn_func = self.make_learn_func(X)

            final_names = dir(self)

            self.register_names_to_del([name for name in final_names if name not in init_names])
        finally:
            self.deploy_mode()
    #

    def learn(self, dataset, batch_size):
        self.learn_mini_batch(dataset.get_batch_design(batch_size))

    def learn_mini_batch(self, X):

        self.learn_func(X)

        if self.monitor.examples_seen % self.print_interval == 0:
            print ""
            print "S3C:"
            self.s3c.status_print()
            print "DBM:"
            self.dbm.status_print()

    def get_weights_format(self):
        return self.s3c.get_weights_format()

class InferenceProcedure:
    """

    Variational inference

    """


    TODO: update this class to work with the PD-DBM, it is just copied from S3C for now


    def get_monitoring_channels(self, V, model):

        #TODO: update this to show updates to h_i and s_i in correct sequence

        rval = {}

        if self.monitor_kl or self.monitor_em_functional:
            obs_history = self.variational_inference(V, return_history = True)

            for i in xrange(1, 2 + len(self.h_new_coeff_schedule)):
                obs = obs_history[i-1]
                if self.monitor_kl:
                    rval['trunc_KL_'+str(i)] = self.truncated_KL(V, model, obs).mean()
                if self.monitor_em_functional:
                    rval['em_functional_'+str(i)] = self.em_functional(V, model, obs).mean()

        return rval


    def __init__(self, h_new_coeff_schedule,
                       s_new_coeff_schedule = None,
                       clip_reflections = False,
                       monitor_kl = False,
                       monitor_em_functional = False,
                       rho = 0.5):
        """Parameters
        --------------
        h_new_coeff_schedule:
            list of coefficients to put on the new value of h on each damped fixed point step
                    (coefficients on s are driven by a special formula)
            length of this list determines the number of fixed point steps
        s_new_coeff_schedule:
            list of coefficients to put on the new value of s on each damped fixed point step
                These are applied AFTER the reflection clipping, which can be seen as a form of
                per-unit damping
                s_new_coeff_schedule must have same length as h_new_coeff_schedule
                if s_new_coeff_schedule is not provided, it will be filled in with all ones,
                    i.e. it will default to no damping beyond the reflection clipping
        clip_reflections, rho : if clip_reflections is true, the update to Mu1[i,j] is
            bounded on one side by - rho * Mu1[i,j] and unbounded on the other side
        """

        if s_new_coeff_schedule is None:
            s_new_coeff_schedule = [ 1.0 for rho in h_new_coeff_schedule ]
        else:
            assert len(s_new_coeff_schedule) == len(h_new_coeff_schedule)

        self.s_new_coeff_schedule = s_new_coeff_schedule

        self.clip_reflections = clip_reflections
        self.h_new_coeff_schedule = h_new_coeff_schedule
        self.monitor_kl = monitor_kl
        self.monitor_em_functional = monitor_em_functional

        self.rho = as_floatX(rho)

        self.model = None

    def em_functional(self, V, model, obs):
        """ Return value is a scalar """
        #TODO: refactor so that this is shared between E-steps

        needed_stats = S3C.expected_log_prob_vhs_needed_stats()

        stats = SufficientStatistics.from_observations( needed_stats = needed_stats,
                                                        X = V, ** obs )

        H_hat = obs['H_hat']
        var_s0_hat = obs['var_s0_hat']
        var_s1_hat = obs['var_s1_hat']

        entropy_term = (model.entropy_hs(H_hat = H_hat, var_s0_hat = var_s0_hat, var_s1_hat = var_s1_hat)).mean()
        likelihood_term = model.expected_log_prob_vhs(stats)

        em_functional = entropy_term + likelihood_term

        return em_functional


    def register_model(self, model):
        self.model = model

    def truncated_KL(self, V, model, obs):
        """ KL divergence between variation and true posterior, dropping terms that don't
            depend on the variational parameters """

        H_hat = obs['H_hat']
        var_s0_hat = obs['var_s0_hat']
        var_s1_hat = obs['var_s1_hat']
        S_hat = obs['S_hat']

        entropy_term = - model.entropy_hs(H_hat = H_hat, var_s0_hat = var_s0_hat, var_s1_hat = var_s1_hat)
        energy_term = model.expected_energy_vhs(V, H_hat = H_hat, S_hat = S_hat,
                                        var_s0_hat = var_s0_hat, var_s1_hat = var_s1_hat)

        KL = entropy_term + energy_term

        return KL

    def init_H_hat(self, V):

        if self.model.recycle_q:
            rval = self.model.prev_H

            if config.compute_test_value != 'off':
                if rval.get_value().shape[0] != V.tag.test_value.shape[0]:
                    raise Exception('E step given wrong test batch size', rval.get_value().shape, V.tag.test_value.shape)
        else:
            #just use the prior
            value =  T.nnet.sigmoid(self.model.bias_hid)
            rval = T.alloc(value, V.shape[0], value.shape[0])

            for rval_value, V_value in get_debug_values(rval, V):
                if rval_value.shape[0] != V_value.shape[0]:
                    debug_error_message("rval.shape = %s, V.shape = %s, element 0 should match but doesn't", str(rval_value.shape), str(V_value.shape))

        return rval

    def init_S_hat(self, V):
        if self.model.recycle_q:
            rval = self.model.prev_Mu1
        else:
            #just use the prior
            value = self.model.mu
            rval = T.alloc(value, V.shape[0], value.shape[0])

        return rval

    def infer_S_hat(self, V, H_hat, S_hat):

        H = H_hat
        Mu1 = S_hat

        for Vv, Hv in get_debug_values(V, H):
            if Vv.shape != (self.model.test_batch_size,self.model.nvis):
                raise Exception('Well this is awkward. We require visible input test tags to be of shape '+str((self.model.test_batch_size,self.model.nvis))+' but the monitor gave us something of shape '+str(Vv.shape)+". The batch index part is probably only important if recycle_q is enabled. It's also probably not all that realistic to plan on telling the monitor what size of batch we need for test tags. the best thing to do is probably change self.model.test_batch_size to match what the monitor does")

            assert Vv.shape[0] == Hv.shape[0]
            assert Hv.shape[1] == self.model.nhid


        mu = self.model.mu
        alpha = self.model.alpha
        W = self.model.W
        B = self.model.B
        w = self.model.w

        BW = B.dimshuffle(0,'x') * W

        HS = H * Mu1

        mean_term = mu * alpha

        data_term = T.dot(V, BW)

        iterm_part_1 = - T.dot(T.dot(HS, W.T), BW)
        iterm_part_2 = w * HS

        interaction_term = iterm_part_1 + iterm_part_2

        for i1v, Vv in get_debug_values(iterm_part_1, V):
            assert i1v.shape[0] == Vv.shape[0]

        debug_interm = mean_term + data_term
        numer = debug_interm + interaction_term

        alpha = self.model.alpha
        w = self.model.w

        denom = alpha + w

        Mu1 =  numer / denom

        return Mu1

    def var_s1_hat(self):
        """Returns the variational parameter for the variance of s given h=1
            This is data-independent so its just a vector of size (nhid,) and
            doesn't take any arguments """

        rval =  1./ (self.model.alpha + self.model.w )

        rval.name = 'var_s1'

        return rval

    def infer_H_hat(self, V, H_hat, S_hat):

        half = as_floatX(.5)
        alpha = self.model.alpha
        w = self.model.w
        mu = self.model.mu
        W = self.model.W
        B = self.model.B
        BW = B.dimshuffle(0,'x') * W

        HS = H_hat * S_hat

        t1f1t1 = V

        t1f1t2 = -T.dot(HS,W.T)
        iterm_corrective = w * H_hat *T.sqr(S_hat)

        t1f1t3_effect = - half * w * T.sqr(S_hat)

        term_1_factor_1 = t1f1t1 + t1f1t2

        term_1 = T.dot(term_1_factor_1, BW) * S_hat + iterm_corrective + t1f1t3_effect

        term_2_subterm_1 = - half * alpha * T.sqr(S_hat)

        term_2_subterm_2 = alpha * S_hat * mu

        term_2_subterm_3 = - half * alpha * T.sqr(mu)

        term_2 = term_2_subterm_1 + term_2_subterm_2 + term_2_subterm_3

        term_3 = self.model.bias_hid

        term_4 = -half * T.log(alpha + self.model.w)

        term_5 = half * T.log(alpha)

        arg_to_sigmoid = term_1 + term_2 + term_3 + term_4 + term_5

        H = T.nnet.sigmoid(arg_to_sigmoid)

        return H

    def damp(self, old, new, new_coeff):
        return new_coeff * new + (1. - new_coeff) * old

    def infer(self, V, return_history = False):
        """

            return_history: if True:
                                returns a list of dictionaries with
                                showing the history of the variational
                                parameters
                                throughout fixed point updates
                            if False:
                                returns a dictionary containing the final
                                variational parameters
        """

        alpha = self.model.alpha


        var_s0_hat = 1. / alpha
        var_s1_hat = self.var_s1_hat()


        H   =    self.init_H_hat(V)
        Mu1 =    self.init_S_hat(V)

        def check_H(my_H, my_V):
            if my_H.dtype != config.floatX:
                raise AssertionError('my_H.dtype should be config.floatX, but they are '
                        ' %s and %s, respectively' % (my_H.dtype, config.floatX))

            allowed_v_types = ['float32']

            if config.floatX == 'float64':
                allowed_v_types.append('float64')

            assert my_V.dtype in allowed_v_types

            if config.compute_test_value != 'off':
                from theano.gof.op import PureOp
                Hv = PureOp._get_test_value(my_H)

                Vv = my_V.tag.test_value

                assert Hv.shape[0] == Vv.shape[0]

        check_H(H,V)

        def make_dict():

            return {
                    'H_hat' : H,
                    'S_hat' : Mu1,
                    'var_s0_hat' : var_s0_hat,
                    'var_s1_hat': var_s1_hat,
                    }

        history = [ make_dict() ]

        for new_H_coeff, new_S_coeff in zip(self.h_new_coeff_schedule, self.s_new_coeff_schedule):

            new_Mu1 = self.infer_S_hat(V, H, Mu1)

            if self.clip_reflections:
                clipped_Mu1 = reflection_clip(Mu1 = Mu1, new_Mu1 = new_Mu1, rho = self.rho)
            else:
                clipped_Mu1 = new_Mu1
            Mu1 = self.damp(old = Mu1, new = clipped_Mu1, new_coeff = new_S_coeff)
            new_H = self.infer_H_hat(V, H, Mu1)

            H = self.damp(old = H, new = new_H, new_coeff = new_H_coeff)

            check_H(H,V)

            history.append(make_dict())

        if return_history:
            return history
        else:
            return history[-1]

class Grad_M_Step:

    TODO: roll this into the main class's make_learn_func somehow

    """ A partial M-step based on gradient ascent.
        More aggressive M-steps are possible but didn't work particularly well in practice
        on STL-10/CIFAR-10
    """

    def __init__(self, learning_rate, B_learning_rate_scale  = 1,
            W_learning_rate_scale = 1, p_penalty = 0.0, B_penalty = 0.0, alpha_penalty = 0.0):
        self.learning_rate = np.cast[config.floatX](float(learning_rate))

        self.B_learning_rate_scale = np.cast[config.floatX](float(B_learning_rate_scale))
        self.W_learning_rate_scale = np.cast[config.floatX](float(W_learning_rate_scale))
        self.p_penalty = as_floatX(p_penalty)
        self.B_penalty = as_floatX(B_penalty)
        self.alpha_penalty = as_floatX(alpha_penalty)

    def get_updates(self, model, stats, H_hat, S_hat):

        params = model.get_params()

        obj = model.expected_log_prob_vhs(stats, H_hat, S_hat) - T.mean(model.p) * self.p_penalty - T.mean(model.B)*self.B_penalty-T.mean(model.alpha)*self.alpha_penalty


        constants = set(stats.d.values()).union([H_hat, S_hat])

        grads = T.grad(obj, params, consider_constant = constants)

        updates = {}

        for param, grad in zip(params, grads):
            learning_rate = self.learning_rate

            if param is model.W:
                learning_rate = learning_rate * self.W_learning_rate_scale

            if param is model.B_driver:
                #can't use *= since this is a numpy ndarray now
                learning_rate = learning_rate * self.B_learning_rate_scale

            if param is model.W and model.constrain_W_norm:
                #project the gradient into the tangent space of the unit hypersphere
                #see "On Gradient Adaptation With Unit Norm Constraints"
                #this is the "true gradient" method on a sphere
                #it computes the gradient, projects the gradient into the tangent space of the sphere,
                #then moves a certain distance along a geodesic in that direction

                g_k = learning_rate * grad

                h_k = g_k -  (g_k*model.W).sum(axis=0) * model.W

                theta_k = T.sqrt(1e-8+T.sqr(h_k).sum(axis=0))

                u_k = h_k / theta_k

                updates[model.W] = T.cos(theta_k) * model.W + T.sin(theta_k) * u_k

            else:
                pparam = param

                inc = learning_rate * grad

                updated_param = pparam + inc

                updates[param] = updated_param

        return updates

    def needed_stats(self):
        return S3C.expected_log_prob_vhs_needed_stats()

    def get_monitoring_channels(self, V, model):

        hid_observations = model.e_step.variational_inference(V)

        stats = SufficientStatistics.from_observations(needed_stats = S3C.expected_log_prob_vhs_needed_stats(),
                V = V, **hid_observations)

        H_hat = hid_observations['H_hat']
        S_hat = hid_observations['S_hat']

        obj = model.expected_log_prob_vhs(stats, H_hat, S_hat)

        return { 'expected_log_prob_vhs' : obj }

