"""Separate targeted M88 claim; original attempts and original claim stay intact."""
import hashlib,json
from app.m88_state import Journal,ledger,write,stamp

CLAIM='m88_targeted_verification'
LIMIT=13


def prefix_sha(attempts: list[dict]) -> str:
    return hashlib.sha256(json.dumps(attempts,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class TargetedJournal(Journal):
    def __init__(self,path,plan_sha: str,plan: dict):
        super().__init__(path,plan_sha)
        self.plan=plan

    def history(self) -> dict:
        data=ledger(self.path)
        if (data.get('m88_operation')!=self.plan['original_operation_sha256']
                or prefix_sha(data['attempts'][:7])!=self.plan['original_attempts_sha256']):
            raise ValueError('Original M88 history changed')
        return data

    def start(self) -> None:
        data=self.history()
        if data.get(CLAIM) is not None or data['attempts_used']!=7:
            raise PermissionError('Targeted verification already claimed or ledger advanced; recovery only')
        if data['attempts_used']+LIMIT>49:raise PermissionError('Insufficient cumulative budget')

    def reserve(self,phase: str,candidate_id: str | None) -> int:
        allowed={r['candidate_id'] for r in self.plan['targets']}
        if (phase not in ('authentication','detail','offers','fees_FBA','fees_FBM')
                or (candidate_id is not None if phase=='authentication' else candidate_id not in allowed)):
            raise ValueError('Targeted phase/source outside reviewed scope')
        data=self.history()
        if data.get(CLAIM) not in (None,self.plan_sha):raise PermissionError('Different targeted claim')
        own=[r for r in data['attempts'][7:] if r.get('plan_sha256')==self.plan_sha]
        if len(own)!=len(data['attempts'])-7:raise ValueError('Unrelated continuation attempts')
        required='authentication' if phase=='detail' else 'detail' if phase=='offers' else 'offers'
        if phase!='authentication' and not any(r['phase']==required and r['status']=='COMPLETE'
                and (required=='authentication' or r['candidate_id']==candidate_id) for r in own):
            raise PermissionError('Required earlier phase not completed')
        if (len(own)>=LIMIT or data['attempts_used']>=49 or any(r['status']!='COMPLETE' for r in own)
                or sum(r['phase']==phase for r in own)>=(1 if phase=='authentication' else 3)
                or any(r['phase']==phase and r['candidate_id']==candidate_id for r in own)):
            raise PermissionError('Budget, repeated phase or uncertain prior attempt')
        number=data['attempts_used']+1
        data[CLAIM]=self.plan_sha
        data['attempts_used']=number
        data['attempts'].append(dict(number=number,phase=phase,candidate_id=candidate_id,
            plan_sha256=self.plan_sha,status='RESERVED',reserved_at=stamp()))
        write(self.path,data,replace=True)
        return number
