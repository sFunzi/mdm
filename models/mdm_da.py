"""
Mixed Dependencies - Hidden Markov Models for Multi-resident Activity Recognition 
with Data Association (applying to CASAS data)
Son N. Tran, CSIRO
email: sontn.fz@gmail.com
===========================================================
Models:
    - MDM_DA
Sensors' state representation
    - Discrete
    - Vector 1: Vector of sensors' values
    - Vector 2: Binary vector of changing states, i.e 1 for sensor whose state is changed
    - Vector 3: One-hot vector for which sensor is seen when the activities happen
"""
import numpy as np
from scipy.optimize import linprog
import math

from models.utils import *

#EPSILON = 0.00001
EPSILON = 0.00000000000000001
#ALPHA = 0.915 # 0.91
class MDM_DA(object):
    def __init__(self,dataset,alpha=0,beta=0,gamma=0,state_type='dis'):
        if dataset is not None:
            self.state_type = state_type
            self.dataset = dataset
            self.alpha = alpha
            self.beta = beta
            self.gamma = gamma
            
            self.spr_act_num = spr_act_num = dataset.separate_act_nums()
            self.cmb_act_num = cmb_act_num = dataset.total_combined_acts()
            self.sen_num     = sen_num     = dataset.sensor_num()
            self.sen_val_num = sen_val_num = dataset.total_sensor_values()
            self.rnum        = rnum        = dataset.resident_num()

            self.prior = np.zeros((1,cmb_act_num),dtype=np.float)
            
            self.tweights = np.zeros((cmb_act_num,cmb_act_num),dtype=np.float)
            if state_type=="dis":
                self.xsize = sen_val_num + 1
                self.eweights = []
            elif state_type=="vec1" or state_type=="vec2" or state_type=="vec3":
                self.xsize = sen_num 
                self.eweights = []
                self.dataset.set_vector_type(int(state_type[-1])) 
            else:
                return
    
    def estimate_params(self):
        _eweights = []
        _spr_tweights = []   # cross transition
        _prl_tweights = []   # parallel transition
        
        for r in range(self.rnum):
            
            if self.state_type=="dis":
                _eweights.append(np.zeros((self.spr_act_num[r],self.xsize),dtype=float))
            else:
                _eweights.append(np.zeros((self.spr_act_num[r],self.xsize,2),dtype=float))
            
            _spr_tweights.append(np.zeros((self.cmb_act_num,self.spr_act_num[r]),dtype=float))
            _prl_tweights.append(np.zeros((self.spr_act_num[r],self.spr_act_num[r]),dtype=float))
            
        _cmb_tweights = np.zeros((self.cmb_act_num,self.cmb_act_num),dtype=float)
        
        # update
        while True:
            prev_act,curr_act,sensor = self.dataset.next()
            # Update transaction probability table
            # tweights[j',j] = p^k(j|j')
            if curr_act is not None:
                cmb_curr_act = self.dataset.act_map(curr_act)
            else:
                break

            if prev_act is not None:
                cmb_prev_act = self.dataset.act_map(prev_act)
                for r in range(self.rnum):
                    # Separate mode
                    _spr_tweights[r][cmb_prev_act,self.dataset.spr_act_map(curr_act[r],r)] +=1
                    _prl_tweights[r][self.dataset.spr_act_map(prev_act[r],r),self.dataset.spr_act_map(curr_act[r],r)] +=1
                    
                # Combine mode 
                _cmb_tweights[cmb_prev_act,cmb_curr_act] +=1
               
            # Update emission probability table
            if sensor is not None:
                for r in range(self.rnum):
                    if self.state_type=="dis":
                        sensor_v = 0
                        if curr_act[r] > 0:
                            sensor_v = self.dataset.sensor_map(sensor) + 1 # No sensor activated is also a state
                        _eweights[r][self.dataset.spr_act_map(curr_act[r],r),sensor_v] +=1
                    else:
                        #NOT DOING
                        raise ValueError('Not implemented')

        #priors
        _spr_priors = self.dataset.get_prior(0)
        _cmb_priors = self.dataset.get_prior(1)

        # Copy to count
        _spr_priors_count   = _spr_priors
        _cmb_priors_count   = _cmb_priors
        _spr_tweights_count = _spr_tweights
        _prl_tweights_count = _prl_tweights
        _cmb_tweights_count = _cmb_tweights
        
        # Laplace Smoothing & Normalize
        for r in range(len(_spr_priors)):
            _spr_priors[r] = (_spr_priors[r]+EPSILON)/(np.sum(_spr_priors[r])+EPSILON*self.spr_act_num[r])
            _spr_priors[r] = np.log2(_spr_priors[r])

        _cmb_priors = (_cmb_priors+EPSILON)/(np.sum(_cmb_priors)+EPSILON*self.cmb_act_num)
        _cmb_priors = np.log2(_cmb_priors)
            
        for r in range(self.rnum):
            if self.state_type=="dis":
                _eweights[r] = (_eweights[r]+EPSILON)/(np.sum(_eweights[r],axis=1)+EPSILON*self.xsize)[:,np.newaxis]
            else:
                _eweights[r] = (_eweights[r]+EPSILON)/(np.sum(_eweights[r],axis=2)+EPSILON*2)[:,:,np.newaxis]
            _eweights[r] = np.log2(_eweights[r])

        for r in range(self.rnum):
            _spr_tweights[r] = (_spr_tweights[r]+EPSILON)/(np.sum(_spr_tweights[r],axis=1)+EPSILON*self.spr_act_num[r])[:,np.newaxis]
            _spr_tweights[r] = np.log2(_spr_tweights[r])
            
            _prl_tweights[r] = (_prl_tweights[r]+EPSILON)/(np.sum(_prl_tweights[r],axis=1)+EPSILON*self.spr_act_num[r])[:,np.newaxis]
            _prl_tweights[r] = np.log2(_prl_tweights[r])
        
        _cmb_tweights = (_cmb_tweights+EPSILON)/(np.sum(_cmb_tweights,axis=1)+EPSILON*self.cmb_act_num)
        _cmb_tweights = np.log2(_cmb_tweights)

        ####### Linear programing ###############################################################
        if self.alpha==0 and self.beta==0 and self.gamma==0:
            A_eq = np.array([[1,1,1]])
            b_eq = np.array([1])
            
            A_ub = np.array([
                [-1,0,0],
                [0,-1,0],
                [0,0,-1]
            ])
            b_ub = np.array([0,0,0])
            c = [0]*3
            c[0] = np.sum([np.sum(a*b)+np.sum(c*d) for a,b,c,d in zip(_spr_priors_count,_spr_priors,_prl_tweights_count,_prl_tweights)])
            c[1] = np.sum(_cmb_priors_count*_cmb_priors)+np.sum([np.sum(a*b) for a,b, in zip(_spr_tweights_count,_spr_tweights)])
            c[2] = np.sum(_cmb_priors_count* _cmb_priors)+np.sum(_cmb_tweights_count* _cmb_tweights)

            res  = linprog(c,A_eq=A_eq,b_eq=b_eq,A_ub=A_ub,b_ub=b_ub,bounds=(0,None))
            print(res.x)
            self.gamma = res.x[0]
            self.beta = res.x[1]
            self.alpha = res.x[2]
        ####### Combine params ##################################################################
        combined_acts = self.dataset.get_act_dict()
        # for prior 
        self.prior = self.alpha*_cmb_priors
        
        for j in range(self.cmb_act_num):
            for r in range(self.rnum):
                inx = self.dataset.spr_act_map(combined_acts[j][r],r)
                self.prior[0,j] += self.beta*_spr_priors[r][0,inx]
                 
        # for emission
        self.eweights = _eweights

        # for transition
        self.tweights = _cmb_tweights*self.alpha

        for j in range(self.cmb_act_num):
            for r in range(self.rnum):
                inx = self.dataset.spr_act_map(combined_acts[j][r],r)
                for j_ in range(self.cmb_act_num):
                    inx_ = self.dataset.spr_act_map(combined_acts[j_][r],r)
                    # Cross dependencies
                    self.tweights[j_,j] += self.beta*_spr_tweights[r][j_,inx]
                    # Parallel dependencies
                    self.tweights[j_,j] += self.gamma*_prl_tweights[r][inx_,inx]        
        
        #for j in range(self.cmb_act_num):
        #    for r in range(self.rnum):
        #        inx = self.dataset.spr_act_map(combined_acts[j][r],r)
        #        for j_ in range(self.cmb_act_num):
        #            inx_ = self.dataset.spr_act_map(combined_acts[j_][r],r)
        #            self.tweights[j_,j] += (self.beta)*_spr_tweights[r][j_,inx]

                    
                    
    def viterbi(self,X):
        # Doing viterbi
        combined_acts = self.dataset.get_act_dict()
        slen = len(X[0])
        path = np.zeros((slen-1,self.cmb_act_num),dtype=np.int)
        mu = [0]*self.cmb_act_num
        if self.state_type=="dis":
            for i in range(self.cmb_act_num):
                for r in range(self.rnum):
                    act = self.dataset.spr_act_map(combined_acts[i][r],r)
                    mu[i] += self.eweights[r][act,X[r][0]]
            
            mu += self.prior
        else:
           raise ValueError('Not implemented')
            
        for t in range(1,slen):
            mu = self.tweights + np.reshape(mu,[self.cmb_act_num,1])
            mx_inds = np.argmax(mu,axis=0)
            mu = np.transpose(np.amax(mu,axis=0))

            if self.state_type=="dis":
                for i in range(self.cmb_act_num):
                    for r in range(self.rnum):
                        act = self.dataset.spr_act_map(combined_acts[i][r],r)
                        mu[i]+= self.eweights[r][act,X[r][t]]
            else:
                mu = mu + np.sum(self.eweights[:,range(self.xsize),X[r][t]],axis=1)
                #TODO
            path[t-1,:] = mx_inds
        # Extract
        max_inx = np.argmax(mu)
        Y = [-1]*slen
        Y[-1]=max_inx
        for t in range(slen-2,-1,-1):
            max_inx = path[t,max_inx]
            Y[t] = max_inx
        
        return Y
    
    def run(self):
        self.estimate_params()
        if self.dataset.evaluation_type==1:
            valid_acc = 0
            if self.state_type=="dis":
                valid_xs,valid_y = self.dataset.valid_da_dis_sequences()
            else:
                valid_xs,valid_y = self.dataset.valid_da_vec_sequences()
            pred = self.viterbi(valid_xs)
 
            pred = self.dataset.act_rmap(pred)
            # Compute accuracy
            valid_acc = pred_accuracy(pred,valid_y)
            return valid_acc, pred, valid_y
        elif self.dataset.evaluation_type==2:
            # NOT APPLY YET
            raise ValueError('This is not in use')
            pred_all = []
            y_all = []
            print('...validating...')
            while True:
                if self.state_type=="dis":
                    valid_x,valid_y = self.dataset.next_valid_dis_sequences()
                else:
                    valid_x,valid_y = self.dataset.next_valid_vec_sequences()
                if valid_x is None:
                    break
                pred = self.viterbi(valid_x)
                pred_all.extend(pred)
                y_all.extend(valid_y)
               
            pred_all = self.dataset.act_rmap(pred_all)
            # Compute accuracy
            valid_acc = pred_accuracy(pred_all,y_all)

            ##### For testing
            print('.... testing ...')
            pred_all = []
            y_all = []
            while True:
                if self.state_type=="dis":
                    test_x,test_y = self.dataset.next_test_dis_sequences()
                else:
                    test_x,test_y = self.dataset.next_test_vec_sequences()
                if test_x is None:
                    break
                pred = self.viterbi(test_x)
                pred_all.extend(pred)
                y_all.extend(test_y)

            pred_all = self.dataset.act_rmap(pred_all)
            # Compute accuracy
            test_acc = pred_accuracy(pred_all,y_all)

            return valid_acc,test_acc, pred_all, y_all
        else:
            raise ValueError('Evaluation type not set')

    # SET PARAMS:
    def set_prior(self,prior):
        self.prior = np.log2(prior)
        self.hsize = prior.shape[0]
    def set_transitions(self,trans):
        self.tweights = np.log2(trans)
    def set_emmissions(self,emits):
        self.eweights = np.log2(emits)
        self.xsize = emits.shape[1]
        
