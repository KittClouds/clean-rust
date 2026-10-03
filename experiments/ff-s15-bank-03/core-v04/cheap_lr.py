"""Dense bounded cue instrument: deterministic standard L-BFGS, numpy only."""
import numpy as np

class MultinomialLogisticRegression:
    def __init__(self,max_iter=200,l2=1.,fit_intercept=True):
        self.max_iter=max_iter;self.l2=l2;self.fit_intercept=fit_intercept
    def fit(self,X,y):
        self.classes_,Y=np.unique(y,return_inverse=True)
        n,d=X.shape;k=len(self.classes_);D=np.column_stack((X,np.ones(n))) if self.fit_intercept else X
        qd=D.shape[1];p=np.zeros(qd*k);history=[]
        def objective(p):
            W=p.reshape(qd,k);z=D@W;z-=z.max(1,keepdims=True)
            ez=np.exp(z);den=ez.sum(1);P=ez/den[:,None]
            loss=float(np.mean(np.log(den)-z[np.arange(n),Y]))
            reg=W.copy()
            if self.fit_intercept:reg[-1]=0
            loss+=self.l2*np.sum(reg*reg)/(2*n)
            P[np.arange(n),Y]-=1
            return loss,((D.T@P+self.l2*reg)/n).ravel()
        loss,g=objective(p)
        for it in range(self.max_iter):
            q=g.copy();alphas=[]
            for s,yh,rho in reversed(history):
                a=rho*(s@q);alphas.append(a);q-=a*yh
            scale=(history[-1][0]@history[-1][1])/(history[-1][1]@history[-1][1]) if history else 1.
            direction=scale*q
            for (s,yh,rho),a in zip(history,reversed(alphas)):
                direction+=s*(a-rho*(yh@direction))
            direction=-direction
            if g@direction>=0:direction=-g;history=[]
            step=1.
            for _ in range(35):
                candidate=p+step*direction;nl,ng=objective(candidate)
                if np.isfinite(nl) and nl<=loss+1e-4*step*(g@direction):break
                step*=.5
            else:break
            s=candidate-p;yh=ng-g;curv=s@yh
            if curv>1e-12:history=(history+[(s,yh,1/curv)])[-10:]
            p,loss,g=candidate,nl,ng
            if np.linalg.norm(g)<1e-5:break
        W=p.reshape(qd,k);self.coef_=W[:-1] if self.fit_intercept else W
        self.intercept_=W[-1] if self.fit_intercept else np.zeros(k)
        self.n_iter_=it+1;self.grad_norm_=float(np.linalg.norm(g));self.final_loss_=loss
        if not np.isfinite(W).all():raise ValueError('Nonfinite cue learner')
        return self
    def predict(self,X):return self.classes_[np.argmax(X@self.coef_+self.intercept_,axis=1)]
